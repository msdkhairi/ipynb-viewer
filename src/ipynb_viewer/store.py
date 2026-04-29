from __future__ import annotations

import base64
import hashlib
import json
import os
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import CACHE_DIR_NAME, MAX_SECTION_CACHE_ENTRIES
from .rendering import (
    ASSET_ID_RE,
    clean_html,
    code_line_count,
    compact_text,
    decode_base64,
    extract_video_data_url,
    highlight_code,
    image_dimensions,
    infer_mime,
    iter_markdown_headings,
    markdown_to_html,
    mime_extension,
    notebook_code_language,
    source_text,
)


@dataclass(frozen=True)
class Section:
    id: int
    title: str
    level: int
    start: int
    end: int


@dataclass
class ParsedNotebook:
    path: Path
    rel_path: str
    mtime_ns: int
    size: int
    metadata: Dict[str, Any]
    language: str
    language_label: str
    cells: List[Dict[str, Any]]
    sections: List[Section]


def build_sections(cells: List[Dict[str, Any]]) -> List[Section]:
    heads: List[Dict[str, Any]] = []
    for index, cell in enumerate(cells):
        if cell.get("cell_type") != "markdown":
            continue
        for level, title in iter_markdown_headings(source_text(cell.get("source"))):
            heads.append({"level": level, "title": title, "start": index})

    if not heads:
        return [Section(id=0, title="Notebook", level=1, start=0, end=len(cells))]

    sections: List[Section] = []
    if heads[0]["start"] > 0:
        sections.append(Section(id=0, title="Notebook", level=1, start=0, end=heads[0]["start"]))

    for idx, head in enumerate(heads):
        end = len(cells)
        for later in heads[idx + 1 :]:
            if later["level"] <= head["level"]:
                end = later["start"]
                break
        sections.append(
            Section(
                id=len(sections),
                title=head["title"],
                level=head["level"],
                start=head["start"],
                end=end,
            )
        )
    return sections


def section_counts(cells: List[Dict[str, Any]], start: int, end: int) -> Dict[str, Any]:
    markdown_count = 0
    code_count = 0
    output_count = 0
    output_mimes: Dict[str, int] = {}
    first_output_type: Optional[str] = None
    has_heavy_media = False
    for cell in cells[start:end]:
        cell_type = cell.get("cell_type")
        if cell_type == "markdown":
            markdown_count += 1
        elif cell_type == "code":
            code_count += 1
        for output in cell.get("outputs", []) or []:
            output_count += 1
            data = output.get("data") or {}
            if not first_output_type:
                first_output_type = _first_output_type(data, output.get("output_type", "output"))
            for mime in data.keys():
                output_mimes[mime] = output_mimes.get(mime, 0) + 1
                if _is_heavy_mime(mime):
                    has_heavy_media = True
            if "text/html" in data and extract_video_data_url(source_text(data["text/html"])):
                has_heavy_media = True

    estimated_height = max(
        180,
        markdown_count * 140 + code_count * 150 + output_count * 220 + (360 if has_heavy_media else 0),
    )
    return {
        "markdownCount": markdown_count,
        "codeCount": code_count,
        "outputCount": output_count,
        "outputMimes": output_mimes,
        "estimatedHeight": estimated_height,
        "hasHeavyMedia": has_heavy_media,
        "firstOutputType": first_output_type,
    }


def _first_output_type(data: Dict[str, Any], output_type: str) -> str:
    if any(mime.startswith("image/") for mime in data):
        return "image"
    if any(mime.startswith("video/") for mime in data):
        return "video"
    if "text/html" in data:
        return "html-video" if extract_video_data_url(source_text(data["text/html"])) else "html"
    if "text/plain" in data or output_type == "stream":
        return "text"
    if "application/vnd.jupyter.widget-view+json" in data:
        return "widget"
    return output_type


def _is_heavy_mime(mime: str) -> bool:
    return mime.startswith("image/") or mime.startswith("video/") or mime == "text/html"


class NotebookStore:
    def __init__(
        self,
        root: Path,
        default_notebook: Optional[str] = None,
        *,
        cache_dir_name: str = CACHE_DIR_NAME,
        max_section_cache_entries: int = MAX_SECTION_CACHE_ENTRIES,
    ):
        self.root = root.resolve()
        self.default_notebook = default_notebook
        self.cache_dir = self.root / cache_dir_name
        self.cache_dir.mkdir(exist_ok=True)
        self.max_section_cache_entries = max_section_cache_entries
        self._notebooks: Dict[Path, ParsedNotebook] = {}
        self._assets: Dict[str, Dict[str, Any]] = {}
        self._section_cache: OrderedDict[Tuple[Path, int, int, int], Dict[str, Any]] = OrderedDict()

    def resolve_notebook_path(self, value: Optional[str]) -> Path:
        requested = value or self.default_notebook
        if not requested:
            notebooks = self.list_notebooks()
            if not notebooks:
                raise ValueError("No notebooks found under the configured root.")
            requested = notebooks[0]["path"]

        path = Path(requested)
        candidate = path.resolve() if path.is_absolute() else (self.root / path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("Notebook path must stay inside the configured root.")
        if candidate.suffix.lower() != ".ipynb":
            raise ValueError("Only .ipynb files can be opened.")
        if not candidate.exists() or not candidate.is_file():
            raise FileNotFoundError(f"Notebook not found: {requested}")
        return candidate

    def rel_path(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def list_notebooks(self) -> List[Dict[str, Any]]:
        notebooks: List[Dict[str, Any]] = []
        for path in self.root.rglob("*.ipynb"):
            if ".ipynb_checkpoints" in path.parts or _is_inside(path, self.cache_dir):
                continue
            try:
                rel = self.rel_path(path)
            except ValueError:
                continue
            stat = path.stat()
            notebooks.append({"path": rel, "name": path.name, "size": stat.st_size})
        notebooks.sort(key=lambda item: item["path"].lower())
        return notebooks

    def load(self, value: Optional[str]) -> ParsedNotebook:
        path = self.resolve_notebook_path(value)
        stat = path.stat()
        cached = self._notebooks.get(path)
        if cached and cached.mtime_ns == stat.st_mtime_ns and cached.size == stat.st_size:
            return cached

        with path.open("r", encoding="utf-8", errors="replace") as handle:
            notebook = json.load(handle)
        metadata = notebook.get("metadata") if isinstance(notebook.get("metadata"), dict) else {}
        code_language = notebook_code_language(metadata)
        cells = list(notebook.get("cells", []))
        parsed = ParsedNotebook(
            path=path,
            rel_path=self.rel_path(path),
            mtime_ns=stat.st_mtime_ns,
            size=stat.st_size,
            metadata=metadata,
            language=code_language["language"],
            language_label=code_language["languageLabel"],
            cells=cells,
            sections=build_sections(cells),
        )
        self._notebooks[path] = parsed
        self._drop_stale_section_cache(path, parsed.mtime_ns, parsed.size)
        return parsed

    def notebook_summary(self, value: Optional[str]) -> Dict[str, Any]:
        parsed = self.load(value)
        outline = []
        for section in parsed.sections:
            counts = section_counts(parsed.cells, section.start, section.end)
            outline.append(
                {
                    "id": section.id,
                    "title": section.title,
                    "level": section.level,
                    "cellStart": section.start,
                    "cellEnd": section.end,
                    **counts,
                }
            )

        first_title = parsed.sections[0].title if parsed.sections else parsed.path.stem
        return {
            "path": parsed.rel_path,
            "title": first_title,
            "cellCount": len(parsed.cells),
            "sectionCount": len(parsed.sections),
            "size": parsed.size,
            "mtimeNs": str(parsed.mtime_ns),
            "outline": outline,
        }

    def section_payload(self, value: Optional[str], section_id: int) -> Dict[str, Any]:
        parsed = self.load(value)
        if section_id < 0 or section_id >= len(parsed.sections):
            raise ValueError("Section index is out of range.")
        key = (parsed.path, parsed.mtime_ns, parsed.size, section_id)
        if key in self._section_cache:
            payload = self._section_cache.pop(key)
            self._section_cache[key] = payload
            return payload

        section = parsed.sections[section_id]
        serialized = [
            serialize_cell(self, parsed, cell, index)
            for index, cell in enumerate(parsed.cells[section.start : section.end], start=section.start)
        ]
        payload = {
            "notebook": parsed.rel_path,
            "section": {
                "id": section.id,
                "title": section.title,
                "level": section.level,
                "cellStart": section.start,
                "cellEnd": section.end,
                **section_counts(parsed.cells, section.start, section.end),
            },
            "cells": serialized,
        }
        self._remember_section(key, payload)
        return payload

    def register_asset(
        self,
        parsed: ParsedNotebook,
        cell_index: int,
        output_index: int,
        mime: str,
        data: bytes,
    ) -> Dict[str, Any]:
        data_hash = hashlib.sha256(data).hexdigest()
        seed = f"{parsed.rel_path}|{parsed.mtime_ns}|{parsed.size}|{cell_index}|{output_index}|{mime}|{data_hash}"
        asset_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        extension = mime_extension(mime)
        target = self.cache_dir / f"{asset_id}{extension}"
        if not target.exists():
            tmp = target.with_suffix(target.suffix + ".tmp")
            with tmp.open("wb") as handle:
                handle.write(data)
            os.replace(tmp, target)
        asset = {
            "assetId": asset_id,
            "assetUrl": f"/api/asset/{asset_id}",
            "mime": mime,
            "size": len(data),
            **image_dimensions(mime, data),
        }
        self._assets[asset_id] = {"path": target, "mime": mime, "size": len(data)}
        return asset

    def asset_info(self, asset_id: str) -> Optional[Dict[str, Any]]:
        if not ASSET_ID_RE.match(asset_id):
            return None
        info = self._assets.get(asset_id)
        if info:
            return info
        matches = sorted(self.cache_dir.glob(f"{asset_id}.*"))
        if not matches:
            return None
        path = matches[0]
        info = {"path": path, "mime": infer_mime(path), "size": path.stat().st_size}
        self._assets[asset_id] = info
        return info

    def _remember_section(self, key: Tuple[Path, int, int, int], payload: Dict[str, Any]) -> None:
        self._section_cache[key] = payload
        while len(self._section_cache) > self.max_section_cache_entries:
            self._section_cache.popitem(last=False)

    def _drop_stale_section_cache(self, path: Path, mtime_ns: int, size: int) -> None:
        for key in list(self._section_cache.keys()):
            cached_path, cached_mtime, cached_size, _ = key
            if cached_path == path and (cached_mtime != mtime_ns or cached_size != size):
                self._section_cache.pop(key, None)


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def serialize_cell(
    store: NotebookStore,
    parsed: ParsedNotebook,
    cell: Dict[str, Any],
    cell_index: int,
) -> Dict[str, Any]:
    cell_type = cell.get("cell_type", "raw")
    source = source_text(cell.get("source"))
    payload: Dict[str, Any] = {"index": cell_index, "type": cell_type}
    if cell_type == "markdown":
        payload["html"] = markdown_to_html(source)
        payload["source"] = source
    elif cell_type == "code":
        payload["source"] = source
        payload["executionCount"] = cell.get("execution_count")
        payload["language"] = parsed.language
        payload["languageLabel"] = parsed.language_label
        payload["lineCount"] = code_line_count(source)
        payload["highlightedHtml"] = highlight_code(source, parsed.language)
        payload["outputs"] = [
            serialize_output(store, parsed, cell_index, output, output_index)
            for output_index, output in enumerate(cell.get("outputs", []) or [])
        ]
    else:
        payload.update(compact_text(source))
    return payload


def serialize_output(
    store: NotebookStore,
    parsed: ParsedNotebook,
    cell_index: int,
    output: Dict[str, Any],
    output_index: int,
) -> Dict[str, Any]:
    output_type = output.get("output_type", "output")
    if output_type == "stream":
        compact = compact_text(source_text(output.get("text")))
        return {"type": "text", "name": output.get("name", "stream"), **compact}

    if output_type == "error":
        traceback = "\n".join(source_text(line) for line in output.get("traceback", []))
        compact = compact_text(traceback or f"{output.get('ename', 'Error')}: {output.get('evalue', '')}")
        return {
            "type": "error",
            "ename": output.get("ename", "Error"),
            "evalue": output.get("evalue", ""),
            **compact,
        }

    data = output.get("data") or {}
    html_data = data.get("text/html")
    if html_data is not None:
        extracted = extract_video_data_url(source_text(html_data))
        if extracted:
            mime, payload = extracted
            try:
                asset = store.register_asset(
                    parsed,
                    cell_index,
                    output_index,
                    mime,
                    base64.b64decode(payload.encode("ascii"), validate=False),
                )
                return {"type": "video", **asset}
            except Exception as exc:
                return {"type": "unsupported", "label": "video/html", "text": str(exc)}

    for mime in ("image/png", "image/jpeg", "image/gif"):
        if mime in data:
            try:
                asset = store.register_asset(parsed, cell_index, output_index, mime, decode_base64(data[mime]))
                return {"type": "image", **asset}
            except Exception as exc:
                return {"type": "unsupported", "label": mime, "text": str(exc)}

    if "image/svg+xml" in data:
        svg = source_text(data["image/svg+xml"]).encode("utf-8")
        asset = store.register_asset(parsed, cell_index, output_index, "image/svg+xml", svg)
        return {"type": "image", **asset}

    for mime in ("video/mp4", "video/webm", "video/ogg"):
        if mime in data:
            try:
                asset = store.register_asset(parsed, cell_index, output_index, mime, decode_base64(data[mime]))
                return {"type": "video", **asset}
            except Exception as exc:
                return {"type": "unsupported", "label": mime, "text": str(exc)}

    if html_data is not None:
        raw = source_text(html_data)
        return {"type": "html", "html": clean_html(raw)}

    if "application/vnd.jupyter.widget-view+json" in data:
        fallback = source_text(data.get("text/plain")) or "Interactive widget output is not available in this reader."
        return {"type": "unsupported", "label": "widget", **compact_text(fallback)}

    if "text/plain" in data:
        return {"type": "text", **compact_text(source_text(data["text/plain"]))}

    if data:
        labels = ", ".join(sorted(data.keys()))
        fallback = source_text(data.get("text/plain")) or f"Unsupported output: {labels}"
        return {"type": "unsupported", "label": labels, **compact_text(fallback)}

    return {"type": "unsupported", "label": output_type, "text": "Empty output.", "truncated": False}


# Backwards-compatible private names used by the original tests/imports.
_build_sections = build_sections
_section_counts = section_counts
_serialize_cell = serialize_cell
_serialize_output = serialize_output
