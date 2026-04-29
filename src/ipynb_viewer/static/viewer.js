const $ = id => document.getElementById(id);
const config = window.NOTEBOOK_VIEWER_CONFIG || {};
const state = {
  notebooks: [],
  notebook: null,
  path: "",
  section: 0,
  loadedSections: new Set(),
  loadingSections: new Set(),
  sectionCache: new Map(),
  sectionRequests: new Map(),
  loadObserver: null,
  activeFrame: 0,
  progressFrame: 0,
  demoMode: false,
  demoRunId: "",
  demoPollTimer: 0,
  demoRefreshing: false,
  notebookSignature: "",
  maxSectionCacheEntries: config.maxSectionCacheEntries || 24,
  prefetchDistance: config.sectionPrefetchDistance || 1,
};

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 3200);
}

function applyTheme(value) {
  const theme = ["device", "light", "dark"].includes(value) ? value : "device";
  document.body.dataset.theme = theme;
  localStorage.setItem("notebook_viewer_theme", theme);
  $("theme-select").value = theme;
}

async function api(url) {
  const res = await fetch(url);
  const json = await res.json();
  if (!json.ok) throw new Error(json.error || "Request failed");
  return json.data;
}

function fmtBytes(size) {
  if (!size) return "0 B";
  const units = ["B","KB","MB","GB"];
  let value = size, index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function setSkeleton(title = "Loading") {
  $("section-title").textContent = title;
  $("section-meta").textContent = "";
  $("cells").className = "skeleton";
  $("cells").innerHTML = "<span></span><span></span><span></span><span></span>";
}

function renderNotebooks() {
  const select = $("notebook-select");
  select.innerHTML = "";
  for (const notebook of state.notebooks) {
    const option = document.createElement("option");
    option.value = notebook.path;
    option.textContent = notebook.path;
    select.appendChild(option);
  }
  select.value = state.path;
}

function renderOutline() {
  const outline = $("outline");
  outline.innerHTML = "";
  if (!state.notebook || !state.notebook.outline.length) {
    outline.innerHTML = '<div class="empty">No outline</div>';
    return;
  }
  for (const item of state.notebook.outline) {
    const button = document.createElement("button");
    button.className = "outline-item" + (item.id === state.section ? " active" : "");
    button.type = "button";
    button.dataset.sectionId = item.id;
    button.style.setProperty("--indent", `${Math.max(0, item.level - 1) * 14}px`);
    button.innerHTML = `<span class="outline-label"></span><span class="outline-count"></span>`;
    button.querySelector(".outline-label").textContent = item.title;
    button.querySelector(".outline-count").textContent = item.outputCount ? `${item.outputCount}` : "";
    button.addEventListener("click", () => selectSection(item.id));
    outline.appendChild(button);
  }
}

function sectionMetaText(item) {
  if (!item) return "";
  const media = item.hasHeavyMedia ? " - media" : "";
  return `${item.codeCount} code cells - ${item.outputCount} outputs${media} - cells ${item.cellStart + 1}-${item.cellEnd}`;
}

function setActiveSection(id) {
  if (!state.notebook) return;
  state.section = id;
  const item = state.notebook.outline[id];
  $("section-title").textContent = item ? item.title : state.notebook.title || "Notebook";
  $("section-meta").textContent = sectionMetaText(item);
  document.querySelectorAll(".outline-item").forEach(button => {
    button.classList.toggle("active", Number(button.dataset.sectionId) === id);
  });
  const active = document.querySelector(`.outline-item[data-section-id="${id}"]`);
  if (active) active.scrollIntoView({block: "nearest"});
  schedulePrefetchAround(id);
}

async function loadNotebook(path) {
  state.path = path;
  state.section = 0;
  state.loadedSections = new Set();
  state.loadingSections = new Set();
  state.sectionCache = new Map();
  state.sectionRequests = new Map();
  if (state.loadObserver) state.loadObserver.disconnect();
  setSkeleton("Loading");
  try {
    state.notebook = await api(`/api/notebook?path=${encodeURIComponent(path)}`);
    state.notebookSignature = notebookSignature(state.notebook);
    $("notebook-meta").textContent = `${state.notebook.sectionCount} sections - ${state.notebook.cellCount} cells - ${fmtBytes(state.notebook.size)}`;
    renderNotebooks();
    renderOutline();
    renderNotebookShell();
    setupLazyLoading();
    await selectSection(0, true);
    updateProgress();
  } catch (err) {
    showToast(err.message);
    $("cells").className = "empty";
    $("cells").textContent = err.message;
  }
}

function notebookSignature(notebook) {
  if (!notebook) return "";
  return `${notebook.size || 0}:${notebook.mtimeNs || 0}`;
}

function renderDemoStatus(status) {
  const box = $("demo-status");
  const label = $("demo-status-text");
  if (!state.demoMode || !status) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.className = `demo-status ${status.status || "running"}`;
  const total = Math.max(0, Number(status.total) || 0);
  const executed = Math.max(0, Number(status.executed) || 0);
  if (status.status === "complete") {
    label.textContent = `Demo complete · ${executed}/${total} cells`;
  } else if (status.status === "failed") {
    label.textContent = `Demo failed · ${status.error || "see notebook output"}`;
  } else {
    label.textContent = `Running demo · ${executed}/${total} cells`;
  }
}

async function refreshLoadedSectionsFromNotebook() {
  if (!state.path || state.demoRefreshing) return;
  state.demoRefreshing = true;
  try {
    const nextNotebook = await api(`/api/notebook?path=${encodeURIComponent(state.path)}`);
    const nextSignature = notebookSignature(nextNotebook);
    if (nextSignature === state.notebookSignature) return;

    const previousSection = state.section;
    const loaded = [...state.loadedSections];
    state.notebook = nextNotebook;
    state.notebookSignature = nextSignature;
    $("notebook-meta").textContent = `${state.notebook.sectionCount} sections - ${state.notebook.cellCount} cells - ${fmtBytes(state.notebook.size)}`;
    renderOutline();

    state.sectionCache.clear();
    state.sectionRequests.clear();
    state.loadedSections = new Set();
    state.loadingSections = new Set();

    for (const item of state.notebook.outline) {
      const section = document.getElementById(`reader-section-${item.id}`);
      if (!section) continue;
      section.style.setProperty("--estimated-height", `${item.estimatedHeight || 720}px`);
      const meta = section.querySelector(".section-block-meta");
      if (meta) meta.textContent = sectionMetaText(item);
    }

    for (const id of loaded) {
      if (id >= 0 && id < state.notebook.outline.length) await loadSectionBody(id);
    }
    setActiveSection(Math.min(previousSection, Math.max(0, state.notebook.outline.length - 1)));
    updateProgress();
  } catch (err) {
    showToast(err.message || "Could not refresh demo output");
  } finally {
    state.demoRefreshing = false;
  }
}

async function pollDemoStatus() {
  if (!state.demoMode || !state.demoRunId) return;
  try {
    const status = await api(`/api/demo-status?run_id=${encodeURIComponent(state.demoRunId)}`);
    renderDemoStatus(status);
    await refreshLoadedSectionsFromNotebook();
    if (status.status === "running" || status.status === "pending") {
      state.demoPollTimer = setTimeout(pollDemoStatus, 1200);
    }
  } catch (err) {
    showToast(err.message || "Could not read demo status");
    state.demoPollTimer = setTimeout(pollDemoStatus, 2500);
  }
}

async function selectSection(id, firstLoad = false) {
  if (!state.notebook) return;
  setActiveSection(id);
  document.body.classList.remove("outline-open");
  try {
    await loadSectionBody(id);
    const section = document.getElementById(`reader-section-${id}`);
    if (section) {
      if (firstLoad) $("reader").scrollTop = 0;
      else section.scrollIntoView({block: "start", behavior: "smooth"});
    }
  } catch (err) {
    showToast(err.message);
    $("cells").className = "empty";
    $("cells").textContent = err.message;
  }
}

function renderNotebookShell() {
  const cells = $("cells");
  cells.className = "notebook-sections";
  cells.innerHTML = "";
  if (!state.notebook.outline.length) {
    cells.className = "empty";
    cells.textContent = "This notebook has no readable sections.";
    return;
  }
  for (const item of state.notebook.outline) {
    const section = document.createElement("section");
    section.className = "reader-section";
    section.id = `reader-section-${item.id}`;
    section.dataset.sectionId = item.id;
    section.style.setProperty("--estimated-height", `${item.estimatedHeight || 720}px`);
    section.innerHTML = `
      <div class="section-block-head">
        <h2 class="section-block-title"></h2>
        <div class="section-block-meta"></div>
      </div>
      <div class="section-body loading" data-section-body="${item.id}">
        <span></span><span></span><span></span>
      </div>`;
    section.querySelector(".section-block-title").textContent = item.title;
    section.querySelector(".section-block-meta").textContent = sectionMetaText(item);
    cells.appendChild(section);
  }
  setActiveSection(0);
}

function setupLazyLoading() {
  const sections = [...document.querySelectorAll(".reader-section")];
  if (!("IntersectionObserver" in window)) {
    sections.forEach(section => loadSectionBody(Number(section.dataset.sectionId)));
    return;
  }
  state.loadObserver = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const id = Number(entry.target.dataset.sectionId);
      loadSectionBody(id);
      state.loadObserver.unobserve(entry.target);
    }
  }, {root: $("reader"), rootMargin: "700px 0px 900px 0px", threshold: 0.01});
  sections.forEach(section => state.loadObserver.observe(section));
}

function sectionCacheKey(id) {
  return `${state.path}::${id}`;
}

function rememberSection(id, payload) {
  const key = sectionCacheKey(id);
  if (state.sectionCache.has(key)) state.sectionCache.delete(key);
  state.sectionCache.set(key, payload);
  while (state.sectionCache.size > state.maxSectionCacheEntries) {
    const first = state.sectionCache.keys().next().value;
    state.sectionCache.delete(first);
  }
}

async function fetchSectionPayload(id) {
  const key = sectionCacheKey(id);
  if (state.sectionCache.has(key)) {
    const payload = state.sectionCache.get(key);
    state.sectionCache.delete(key);
    state.sectionCache.set(key, payload);
    return payload;
  }
  const payload = await api(`/api/section?path=${encodeURIComponent(state.path)}&section=${id}`);
  rememberSection(id, payload);
  return payload;
}

async function loadSectionBody(id, options = {}) {
  if (state.loadedSections.has(id)) return;
  state.loadingSections.add(id);
  const body = document.querySelector(`[data-section-body="${id}"]`);
  const key = sectionCacheKey(id);
  try {
    let request = state.sectionRequests.get(key);
    if (!request) {
      request = fetchSectionPayload(id);
      state.sectionRequests.set(key, request);
    }
    const payload = await request;
    if (!options.prefetchOnly) {
      renderSectionBody(payload);
      state.loadedSections.add(id);
    }
  } catch (err) {
    if (body && !options.prefetchOnly) {
      body.className = "section-body unsupported";
      body.textContent = err.message || "Could not load this section.";
    }
    if (!options.prefetchOnly) showToast(err.message || "Could not load section");
  } finally {
    state.sectionRequests.delete(key);
    state.loadingSections.delete(id);
    if (body && !options.prefetchOnly) body.classList.remove("loading");
  }
}

function schedulePrefetchAround(id) {
  const run = () => {
    if (!state.notebook) return;
    for (let offset = 1; offset <= state.prefetchDistance; offset += 1) {
      for (const nextId of [id - offset, id + offset]) {
        if (nextId < 0 || nextId >= state.notebook.outline.length) continue;
        if (state.loadedSections.has(nextId) || state.loadingSections.has(nextId)) continue;
        loadSectionBody(nextId, {prefetchOnly: true});
      }
    }
  };
  if ("requestIdleCallback" in window) requestIdleCallback(run, {timeout: 900});
  else setTimeout(run, 140);
}

function renderSectionBody(payload) {
  const body = document.querySelector(`[data-section-body="${payload.section.id}"]`);
  if (!body) return;
  body.className = "section-body";
  body.innerHTML = "";
  if (!payload.cells.length) {
    body.className = "section-body empty";
    body.textContent = "This section is empty.";
    return;
  }
  for (const cell of payload.cells) body.appendChild(renderCell(cell));
}

function updateActiveFromScroll() {
  state.activeFrame = 0;
  if (!state.notebook) return;
  const readerRect = $("reader").getBoundingClientRect();
  const probeY = readerRect.top + 120;
  let activeId = 0;
  for (const section of document.querySelectorAll(".reader-section")) {
    const rect = section.getBoundingClientRect();
    if (rect.top <= probeY) activeId = Number(section.dataset.sectionId);
    else break;
  }
  setActiveSection(activeId);
}

function updateProgress() {
  state.progressFrame = 0;
  const reader = $("reader");
  const max = Math.max(1, reader.scrollHeight - reader.clientHeight);
  const progress = Math.min(1, Math.max(0, reader.scrollTop / max));
  $("reader-progress").style.width = `${progress * 100}%`;
}

function scheduleScrollWork() {
  if (!state.activeFrame) state.activeFrame = requestAnimationFrame(updateActiveFromScroll);
  if (!state.progressFrame) state.progressFrame = requestAnimationFrame(updateProgress);
}

function renderCell(cell) {
  if (cell.type === "markdown") {
    const article = document.createElement("article");
    article.className = "cell markdown";
    article.innerHTML = cell.html || "";
    return article;
  }
  if (cell.type === "code") {
    const article = document.createElement("article");
    article.className = "cell code-cell";
    if (cell.outputs && cell.outputs.length) {
      const outputs = document.createElement("div");
      outputs.className = "outputs";
      for (const output of cell.outputs) outputs.appendChild(renderOutput(output));
      article.appendChild(outputs);
    }
    const details = document.createElement("details");
    details.className = "code-details";
    const summary = document.createElement("summary");
    summary.className = "code-summary";
    summary.textContent = formatCodeCellLabel(cell);
    const pre = document.createElement("pre");
    pre.className = "code";
    const code = document.createElement("code");
    code.className = `language-${cell.language || "text"}`;
    if (cell.highlightedHtml) {
      code.innerHTML = cell.highlightedHtml;
    } else {
      code.textContent = cell.source || "";
    }
    pre.appendChild(code);
    details.appendChild(summary);
    details.appendChild(pre);
    article.appendChild(details);
    return article;
  }
  const pre = document.createElement("pre");
  pre.className = "cell text-output";
  pre.textContent = cell.text || "";
  return pre;
}

function formatCodeCellLabel(cell) {
  const language = cell.languageLabel || (cell.language && cell.language !== "text" ? cell.language : "Code");
  const run = cell.executionCount == null ? "Not run" : `Run ${cell.executionCount}`;
  const lineCount = Number.isFinite(cell.lineCount) ? cell.lineCount : (cell.source || "").split(/\r\n|\r|\n/).filter(Boolean).length;
  const lines = `${lineCount} ${lineCount === 1 ? "line" : "lines"}`;
  return `${language} · ${run} · ${lines}`;
}

function renderOutput(output) {
  const box = document.createElement("div");
  box.className = "output";
  if (output.type === "image") {
    const frame = document.createElement("div");
    frame.className = "media-frame";
    if (output.width && output.height) frame.style.aspectRatio = `${output.width} / ${output.height}`;
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = output.mime || "notebook image output";
    img.src = output.assetUrl;
    if (output.width) img.width = output.width;
    if (output.height) img.height = output.height;
    frame.appendChild(img);
    box.appendChild(frame);
  } else if (output.type === "video") {
    const frame = document.createElement("div");
    frame.className = "media-frame";
    const video = document.createElement("video");
    video.controls = true;
    video.preload = "metadata";
    video.src = output.assetUrl;
    frame.appendChild(video);
    box.appendChild(frame);
  } else if (output.type === "html") {
    box.className += " html-output";
    box.innerHTML = output.html || "";
  } else if (output.type === "error") {
    const pre = document.createElement("pre");
    pre.className = "error-output";
    pre.textContent = output.text || output.evalue || "Error";
    box.appendChild(pre);
  } else if (output.type === "unsupported") {
    const div = document.createElement("div");
    div.className = "unsupported";
    div.textContent = output.text || output.label || "Unsupported output";
    box.appendChild(div);
  } else {
    const pre = document.createElement("pre");
    pre.className = "text-output";
    pre.textContent = output.text || "";
    box.appendChild(pre);
  }
  return box;
}

function setAllCode(open) {
  document.querySelectorAll("details").forEach(detail => { detail.open = open; });
}

async function boot() {
  try {
    const apiConfig = await api("/api/config");
    state.prefetchDistance = apiConfig.sectionPrefetchDistance || state.prefetchDistance;
    state.maxSectionCacheEntries = apiConfig.maxSectionCacheEntries || state.maxSectionCacheEntries;
    state.demoMode = Boolean(apiConfig.demoMode);
    state.demoRunId = apiConfig.demoRunId || "";
    state.notebooks = await api("/api/notebooks");
    if (!state.notebooks.length) throw new Error("No notebooks found under the configured root.");
    const preferred = apiConfig.defaultNotebook || state.notebooks[0].path;
    state.path = state.notebooks.some(item => item.path === preferred) ? preferred : state.notebooks[0].path;
    renderNotebooks();
    await loadNotebook(state.path);
    if (state.demoMode) pollDemoStatus();
  } catch (err) {
    showToast(err.message);
    $("cells").className = "empty";
    $("cells").textContent = err.message;
  }
}

function closeOutline() {
  document.body.classList.remove("outline-open");
}

$("notebook-select").addEventListener("change", event => loadNotebook(event.target.value));
$("theme-select").addEventListener("change", event => applyTheme(event.target.value));
$("expand-code").addEventListener("click", () => setAllCode(true));
$("collapse-code").addEventListener("click", () => setAllCode(false));
$("outline-toggle").addEventListener("click", () => document.body.classList.add("outline-open"));
$("outline-close").addEventListener("click", closeOutline);
$("drawer-backdrop").addEventListener("click", closeOutline);
$("reader").addEventListener("scroll", scheduleScrollWork, {passive: true});
document.addEventListener("keydown", event => {
  if (event.key === "Escape") closeOutline();
});
applyTheme(localStorage.getItem("notebook_viewer_theme") || "device");
boot();
