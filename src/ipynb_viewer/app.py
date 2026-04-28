from __future__ import annotations

from pathlib import Path
from typing import Optional

from flask import Flask, Response, jsonify, render_template, request, send_file

from .config import CACHE_DIR_NAME, MAX_SECTION_CACHE_ENTRIES, SECTION_PREFETCH_DISTANCE
from .store import NotebookStore


def api_error(exc: Exception, status: int = 400):
    if isinstance(exc, FileNotFoundError):
        status = 404
    return jsonify({"ok": False, "error": str(exc)}), status


def create_app(root: str | Path = ".", default_notebook: Optional[str] = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    store = NotebookStore(Path(root), default_notebook)
    app.config["NOTEBOOK_STORE"] = store

    @app.after_request
    def add_headers(response: Response) -> Response:
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html",
            cache_dir_name=CACHE_DIR_NAME,
            section_prefetch_distance=SECTION_PREFETCH_DISTANCE,
            max_section_cache_entries=MAX_SECTION_CACHE_ENTRIES,
        )

    @app.get("/api/config")
    def api_config():
        return jsonify(
            {
                "ok": True,
                "data": {
                    "root": store.root.as_posix(),
                    "defaultNotebook": store.default_notebook or "",
                    "sectionPrefetchDistance": SECTION_PREFETCH_DISTANCE,
                    "maxSectionCacheEntries": MAX_SECTION_CACHE_ENTRIES,
                },
            }
        )

    @app.get("/api/notebooks")
    def api_notebooks():
        try:
            return jsonify({"ok": True, "data": store.list_notebooks()})
        except Exception as exc:
            return api_error(exc)

    @app.get("/api/notebook")
    def api_notebook():
        try:
            return jsonify({"ok": True, "data": store.notebook_summary(request.args.get("path"))})
        except Exception as exc:
            return api_error(exc)

    @app.get("/api/section")
    def api_section():
        try:
            section = int(request.args.get("section", "0"))
            return jsonify({"ok": True, "data": store.section_payload(request.args.get("path"), section)})
        except Exception as exc:
            return api_error(exc)

    @app.get("/api/asset/<asset_id>")
    def api_asset(asset_id: str):
        info = store.asset_info(asset_id)
        if not info:
            return jsonify({"ok": False, "error": "Asset not found."}), 404
        response = send_file(
            info["path"],
            mimetype=info["mime"],
            conditional=True,
            etag=True,
            last_modified=info["path"].stat().st_mtime,
        )
        response.headers["Accept-Ranges"] = "bytes"
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    return app

