from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from .config import CACHE_DIR_NAME, DEMO_RUNS_DIR_NAME


DEMO_PACKAGE = "ipynb_viewer.demo_notebooks"
DEMO_NAME_RE = re.compile(r"^[a-z0-9_]+$")
DEMO_EXTRA_HINT = 'python -m pip install "ipynb-local-viewer[demo]"'


@dataclass(frozen=True)
class DemoInfo:
    name: str
    title: str
    description: str
    filename: str


@dataclass(frozen=True)
class DemoRun:
    run_id: str
    demo: str
    root: Path
    notebook: str
    path: Path


@dataclass
class DemoRunStatus:
    run_id: str
    demo: str
    status: str
    executed: int
    total: int
    notebook: str
    error: str = ""
    updated_at: float = 0.0

    def payload(self) -> Dict[str, Any]:
        return {
            "runId": self.run_id,
            "demo": self.demo,
            "status": self.status,
            "executed": self.executed,
            "total": self.total,
            "notebook": self.notebook,
            "error": self.error,
            "updatedAt": self.updated_at,
        }


class DemoError(RuntimeError):
    pass


class UnknownDemoError(DemoError):
    pass


class MissingDemoDependenciesError(DemoError):
    def __init__(self, missing: Iterable[str]):
        names = ", ".join(sorted(set(missing)))
        super().__init__(f"Demo execution needs optional dependencies: {names}. Install them with: {DEMO_EXTRA_HINT}")
        self.missing = sorted(set(missing))


DEMO_NOTEBOOKS: Dict[str, DemoInfo] = {
    "quickstart": DemoInfo(
        name="quickstart",
        title="Quickstart Tour",
        description="First-run tour of outline navigation, output-first reading, tables, charts, and sanitized HTML.",
        filename="quickstart.ipynb",
    ),
    "signal_lab": DemoInfo(
        name="signal_lab",
        title="Signal Lab",
        description="Offline scientific workflow with filtering, frequency analysis, summary tables, and spectrograms.",
        filename="signal_lab.ipynb",
    ),
    "visual_story": DemoInfo(
        name="visual_story",
        title="Visual Story",
        description="Generated image, color-field, and SVG outputs served through lazy media assets.",
        filename="visual_story.ipynb",
    ),
    "interactive_charts": DemoInfo(
        name="interactive_charts",
        title="Interactive Charts",
        description="Pandas, seaborn, matplotlib, and Plotly-generated HTML with a sanitized fallback.",
        filename="interactive_charts.ipynb",
    ),
    "motion_demo": DemoInfo(
        name="motion_demo",
        title="Motion Demo",
        description="Tiny packaged MP4 and generated frame strip for checking lazy video and image output.",
        filename="motion_demo.ipynb",
    ),
    "rich_report": DemoInfo(
        name="rich_report",
        title="Rich Report",
        description="Executive-style report with KPI tables, charts, generated imagery, and sanitized HTML.",
        filename="rich_report.ipynb",
    ),
}

_STATUS_LOCK = threading.Lock()
_STATUSES: Dict[str, DemoRunStatus] = {}


def normalize_demo_name(name: str) -> str:
    normalized = (name or "").strip().lower().replace("-", "_")
    if not DEMO_NAME_RE.match(normalized):
        raise UnknownDemoError("Demo names may contain only lowercase letters, numbers, and underscores.")
    if normalized not in DEMO_NOTEBOOKS:
        available = ", ".join(sorted(DEMO_NOTEBOOKS))
        raise UnknownDemoError(f"Unknown demo '{name}'. Available demos: {available}")
    return normalized


def list_demo_notebooks() -> list[Dict[str, str]]:
    return [
        {"name": info.name, "title": info.title, "description": info.description}
        for info in sorted(DEMO_NOTEBOOKS.values(), key=lambda item: item.name)
    ]


def normalize_demo_argv(argv: Optional[list[str]]) -> Optional[list[str]]:
    if argv is None:
        return None
    normalized: list[str] = []
    for arg in argv:
        if arg.startswith("--demo."):
            demo = arg[len("--demo.") :]
            if not demo:
                normalized.append(arg)
            else:
                normalized.extend(["--demo", demo])
        else:
            normalized.append(arg)
    return normalized


def prepare_demo_run(name: str, base_root: str | Path = ".") -> DemoRun:
    demo_name = normalize_demo_name(name)
    info = DEMO_NOTEBOOKS[demo_name]
    base = Path(base_root).expanduser().resolve()
    run_id = f"{demo_name}-{int(time.time() * 1000)}-{os.getpid()}"
    run_root = base / CACHE_DIR_NAME / DEMO_RUNS_DIR_NAME / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    notebook_name = info.filename
    target = run_root / notebook_name

    package_files = resources.files(DEMO_PACKAGE)
    resource = package_files.joinpath(info.filename)
    with resources.as_file(resource) as source:
        shutil.copyfile(source, target)

    run = DemoRun(run_id=run_id, demo=demo_name, root=run_root, notebook=notebook_name, path=target)
    register_demo_status(run, status="pending", executed=0, total=0)
    return run


def register_demo_status(run: DemoRun, *, status: str, executed: int, total: int, error: str = "") -> None:
    with _STATUS_LOCK:
        _STATUSES[run.run_id] = DemoRunStatus(
            run_id=run.run_id,
            demo=run.demo,
            status=status,
            executed=executed,
            total=total,
            notebook=run.notebook,
            error=error,
            updated_at=time.time(),
        )


def update_demo_status(
    run_id: str,
    *,
    status: Optional[str] = None,
    executed: Optional[int] = None,
    total: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    with _STATUS_LOCK:
        current = _STATUSES.get(run_id)
        if current is None:
            return
        if status is not None:
            current.status = status
        if executed is not None:
            current.executed = executed
        if total is not None:
            current.total = total
        if error is not None:
            current.error = error
        current.updated_at = time.time()


def get_demo_status(run_id: str) -> Optional[Dict[str, Any]]:
    with _STATUS_LOCK:
        current = _STATUSES.get(run_id)
        return current.payload() if current is not None else None


def ensure_demo_dependencies() -> None:
    _load_execution_dependencies()


def start_demo_execution(run: DemoRun) -> threading.Thread:
    thread = threading.Thread(target=execute_demo_notebook, args=(run,), name=f"demo-{run.run_id}", daemon=True)
    thread.start()
    return thread


def execute_demo_notebook(
    run: DemoRun,
    *,
    dependency_loader: Optional[Callable[[], tuple[Any, Any]]] = None,
) -> None:
    nbformat: Any
    notebook_client: Any
    try:
        if dependency_loader is None:
            dependency_loader = _load_execution_dependencies
        nbformat, notebook_client = dependency_loader()
        notebook = nbformat.read(run.path, as_version=4)
        total = _clear_code_outputs(notebook)
        _ensure_python_metadata(notebook)
        update_demo_status(run.run_id, status="running", executed=0, total=total, error="")
        _write_notebook_atomic(nbformat, notebook, run.path)

        client = notebook_client(
            notebook,
            timeout=120,
            kernel_name="python3",
            resources={"metadata": {"path": str(run.root)}},
            allow_errors=False,
        )

        executed = 0
        with client.setup_kernel():
            for index, cell in enumerate(_notebook_cells(notebook)):
                if not _is_executable_code_cell(cell):
                    continue
                client.execute_cell(cell, index)
                executed += 1
                update_demo_status(run.run_id, status="running", executed=executed, total=total, error="")
                _write_notebook_atomic(nbformat, notebook, run.path)

        _write_notebook_atomic(nbformat, notebook, run.path)
        update_demo_status(run.run_id, status="complete", executed=executed, total=total, error="")
    except Exception as exc:
        error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        try:
            if "nbformat" in locals() and "notebook" in locals():
                _write_notebook_atomic(nbformat, notebook, run.path)
        finally:
            update_demo_status(run.run_id, status="failed", error=error)


def _load_execution_dependencies() -> tuple[Any, Any]:
    required = {
        "IPython": "IPython",
        "ipykernel": "ipykernel",
        "matplotlib": "matplotlib",
        "nbclient": "nbclient",
        "nbformat": "nbformat",
        "numpy": "numpy",
        "pandas": "pandas",
        "PIL": "Pillow",
        "plotly": "plotly",
        "scipy": "scipy",
        "seaborn": "seaborn",
    }
    missing: list[str] = []
    for module, package_name in required.items():
        try:
            __import__(module)
        except Exception:
            missing.append(package_name)
    if missing:
        raise MissingDemoDependenciesError(missing)

    import nbformat
    from nbclient import NotebookClient

    return nbformat, NotebookClient


def _notebook_cells(notebook: Any) -> list[Any]:
    return notebook["cells"]


def _source_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(str(part) for part in value)
    return str(value)


def _is_executable_code_cell(cell: Any) -> bool:
    return cell.get("cell_type") == "code" and bool(_source_text(cell.get("source")).strip())


def _clear_code_outputs(notebook: Any) -> int:
    total = 0
    for cell in _notebook_cells(notebook):
        if cell.get("cell_type") != "code":
            continue
        cell["outputs"] = []
        cell["execution_count"] = None
        if _source_text(cell.get("source")).strip():
            total += 1
    return total


def _ensure_python_metadata(notebook: Any) -> None:
    metadata = notebook.setdefault("metadata", {})
    metadata["kernelspec"] = {
        "display_name": f"Python {sys.version_info.major}",
        "language": "python",
        "name": "python3",
    }
    metadata["language_info"] = {
        "name": "python",
        "pygments_lexer": "ipython3",
    }


def _write_notebook_atomic(nbformat: Any, notebook: Any, path: Path) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        nbformat.write(notebook, handle)
    os.replace(tmp, path)
