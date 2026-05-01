import base64
import contextlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

import ipynb_viewer as viewer
from ipynb_viewer.cli import build_parser, main
from ipynb_viewer.demos import (
    DemoRun,
    MissingDemoDependenciesError,
    execute_demo_notebook,
    get_demo_status,
    list_demo_notebooks,
    normalize_demo_argv,
    prepare_demo_run,
    register_demo_status,
)


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lWf9UwAAAABJRU5ErkJggg=="
)


def write_notebook(root: Path, name: str, cells, metadata=None):
    path = root / name
    payload = {
        "cells": cells,
        "metadata": metadata or {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class NotebookViewerTests(unittest.TestCase):
    def test_heading_sections_and_synthetic_fallback(self):
        cells = [
            {"cell_type": "markdown", "source": "# Alpha\nintro"},
            {"cell_type": "code", "source": "a = 1", "outputs": []},
            {"cell_type": "markdown", "source": ["## Detail\n", "notes"]},
            {"cell_type": "code", "source": "b = 2", "outputs": []},
            {"cell_type": "markdown", "source": "# Beta"},
        ]

        sections = viewer._build_sections(cells)

        self.assertEqual(
            [(s.title, s.level, s.start, s.end) for s in sections],
            [("Alpha", 1, 0, 4), ("Detail", 2, 2, 4), ("Beta", 1, 4, 5)],
        )

        fallback = viewer._build_sections([{"cell_type": "code", "source": "x = 1", "outputs": []}])
        self.assertEqual((fallback[0].title, fallback[0].start, fallback[0].end), ("Notebook", 0, 1))

        with_preamble = viewer._build_sections(
            [
                {"cell_type": "code", "source": "shown_before_heading()", "outputs": []},
                {"cell_type": "markdown", "source": "# First"},
            ]
        )
        self.assertEqual(
            [(s.title, s.start, s.end) for s in with_preamble],
            [("Notebook", 0, 1), ("First", 1, 2)],
        )

    def test_source_string_and_list_are_rendered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_notebook(
                root,
                "sample.ipynb",
                [
                    {"cell_type": "markdown", "source": "# Section\n\nA paragraph."},
                    {
                        "cell_type": "code",
                        "execution_count": 3,
                        "source": ["x = 1\n", "print(x)"],
                        "outputs": [{"output_type": "stream", "name": "stdout", "text": ["1\n"]}],
                    },
                ],
            )
            app = viewer.create_app(root=root, default_notebook="sample.ipynb")
            client = app.test_client()

            notebook = client.get("/api/notebook?path=sample.ipynb")
            self.assertEqual(notebook.status_code, 200)
            self.assertEqual(notebook.json["data"]["outline"][0]["title"], "Section")

            section = client.get("/api/section?path=sample.ipynb&section=0")
            self.assertEqual(section.status_code, 200)
            cells = section.json["data"]["cells"]
            self.assertIn("<p>A paragraph.</p>", cells[0]["html"])
            self.assertEqual(cells[1]["source"], "x = 1\nprint(x)")
            self.assertEqual(cells[1]["language"], "python")
            self.assertEqual(cells[1]["languageLabel"], "Python")
            self.assertEqual(cells[1]["lineCount"], 2)
            self.assertIn('class="nb"', cells[1]["highlightedHtml"])
            self.assertEqual(cells[1]["outputs"][0]["text"], "1\n")

    def test_code_cells_include_highlight_metadata_and_escape_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_notebook(
                root,
                "highlight.ipynb",
                [
                    {"cell_type": "markdown", "source": "# Highlight"},
                    {
                        "cell_type": "code",
                        "execution_count": 4,
                        "source": ["def hello(x):\n", "    return \"<script>alert(x)</script>\"\n"],
                        "outputs": [],
                    },
                ],
                metadata={"language_info": {"name": "python", "pygments_lexer": "python"}},
            )
            app = viewer.create_app(root=root, default_notebook="highlight.ipynb")
            client = app.test_client()

            response = client.get("/api/section?path=highlight.ipynb&section=0")

            self.assertEqual(response.status_code, 200)
            cell = response.json["data"]["cells"][1]
            self.assertEqual(cell["language"], "python")
            self.assertEqual(cell["languageLabel"], "Python")
            self.assertEqual(cell["lineCount"], 2)
            self.assertIn('class="k"', cell["highlightedHtml"])
            self.assertNotIn("<script>", cell["highlightedHtml"])
            self.assertIn("&lt;script&gt;", cell["highlightedHtml"])

    def test_unknown_code_language_uses_code_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_notebook(
                root,
                "unknown.ipynb",
                [
                    {"cell_type": "markdown", "source": "# Unknown"},
                    {"cell_type": "code", "execution_count": None, "source": "not real syntax", "outputs": []},
                ],
                metadata={"language_info": {"name": "mysterylang"}},
            )
            app = viewer.create_app(root=root, default_notebook="unknown.ipynb")
            client = app.test_client()

            response = client.get("/api/section?path=unknown.ipynb&section=0")

            self.assertEqual(response.status_code, 200)
            cell = response.json["data"]["cells"][1]
            self.assertEqual(cell["language"], "text")
            self.assertEqual(cell["languageLabel"], "Code")

    def test_outputs_become_safe_descriptors_and_assets_are_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_payload = base64.b64encode(PNG_BYTES).decode("ascii")
            video_payload = base64.b64encode(b"fake-mp4-data").decode("ascii")
            video_html = f'<video controls><source src="data:video/mp4;base64,{video_payload}"></video>'
            write_notebook(
                root,
                "outputs.ipynb",
                [
                    {"cell_type": "markdown", "source": "# Outputs"},
                    {
                        "cell_type": "code",
                        "execution_count": 1,
                        "source": "display(outputs)",
                        "outputs": [
                            {"output_type": "display_data", "data": {"image/png": image_payload, "text/plain": "fig"}},
                            {"output_type": "display_data", "data": {"text/html": video_html}},
                            {
                                "output_type": "display_data",
                                "data": {"text/html": "<script>alert(1)</script><table><tr><td>ok</td></tr></table>"},
                            },
                            {
                                "output_type": "display_data",
                                "data": {
                                    "application/vnd.jupyter.widget-view+json": {"model_id": "abc"},
                                    "text/plain": "widget fallback",
                                },
                            },
                        ],
                    },
                ],
            )
            app = viewer.create_app(root=root, default_notebook="outputs.ipynb")
            client = app.test_client()

            first = client.get("/api/section?path=outputs.ipynb&section=0")
            self.assertEqual(first.status_code, 200)
            payload = first.json["data"]
            outputs = payload["cells"][1]["outputs"]
            self.assertEqual([item["type"] for item in outputs], ["image", "video", "html", "unsupported"])
            self.assertNotIn(image_payload, json.dumps(payload))
            self.assertNotIn(video_payload, json.dumps(payload))
            self.assertNotIn("<script", outputs[2]["html"])
            self.assertIn("ok", outputs[2]["html"])
            self.assertEqual(outputs[0]["width"], 1)
            self.assertEqual(outputs[0]["height"], 1)

            image = client.get(outputs[0]["assetUrl"])
            self.assertEqual(image.status_code, 200)
            self.assertEqual(image.mimetype, "image/png")
            self.assertEqual(image.data, PNG_BYTES)
            image.close()

            video = client.get(outputs[1]["assetUrl"], headers={"Range": "bytes=0-3"})
            self.assertEqual(video.status_code, 206)
            self.assertEqual(video.headers.get("Accept-Ranges"), "bytes")
            self.assertEqual(video.data, b"fake")
            video.close()

            cache_files = sorted((root / ".notebook_viewer_cache").glob("*"))
            second = client.get("/api/section?path=outputs.ipynb&section=0")
            self.assertEqual(second.status_code, 200)
            self.assertEqual(sorted((root / ".notebook_viewer_cache").glob("*")), cache_files)
            self.assertEqual(
                second.json["data"]["cells"][1]["outputs"][0]["assetUrl"],
                outputs[0]["assetUrl"],
            )

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            write_notebook(root, "safe.ipynb", [{"cell_type": "markdown", "source": "# Safe"}])
            app = viewer.create_app(root=root, default_notebook="safe.ipynb")
            client = app.test_client()

            response = client.get("/api/notebook?path=../evil.ipynb")

            self.assertEqual(response.status_code, 400)
            self.assertFalse(response.json["ok"])

    def test_viewer_html_includes_theme_picker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_notebook(root, "theme.ipynb", [{"cell_type": "markdown", "source": "# Theme"}])
            app = viewer.create_app(root=root, default_notebook="theme.ipynb")
            client = app.test_client()

            response = client.get("/")

            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn('id="theme-control"', html)
            self.assertIn('role="group" aria-label="Theme"', html)
            self.assertIn('data-theme-option="device"', html)
            self.assertIn('data-theme-option="light"', html)
            self.assertIn('data-theme-option="dark"', html)
            self.assertIn('aria-label="Use device theme"', html)
            self.assertIn('aria-pressed="true"', html)
            self.assertIn('id="expand-code"', html)
            self.assertIn('id="collapse-code"', html)

    def test_static_assets_include_dark_motion_and_lazy_cache_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_notebook(root, "theme.ipynb", [{"cell_type": "markdown", "source": "# Theme"}])
            app = viewer.create_app(root=root, default_notebook="theme.ipynb")
            client = app.test_client()

            css = client.get("/static/viewer.css")
            js = client.get("/static/viewer.js")

            self.assertEqual(css.status_code, 200)
            self.assertEqual(js.status_code, 200)
            css_text = css.get_data(as_text=True)
            js_text = js.get_data(as_text=True)
            self.assertIn("--sidebar-bg:#0f1511", css_text)
            self.assertIn("prefers-reduced-motion", css_text)
            self.assertIn("requestIdleCallback", js_text)
            self.assertIn("sectionCache", js_text)
            self.assertIn("fetchSectionPayload", js_text)
            self.assertIn("--code-keyword", css_text)
            self.assertIn(".code .k", css_text)
            self.assertIn("--progress-track", css_text)
            self.assertIn("height:var(--progress-height)", css_text)
            self.assertIn("formatCodeCellLabel", js_text)
            self.assertIn("Run ${cell.executionCount}", js_text)
            self.assertIn("pollDemoStatus", js_text)
            self.assertIn(".demo-status", css_text)
            self.assertIn("[data-theme-option]", js_text)
            self.assertIn('setAttribute("aria-pressed"', js_text)
            self.assertIn(".theme-option.active", css_text)
            self.assertIn(".action-btn", css_text)
            css.close()
            js.close()

    def test_cli_parser_accepts_package_ready_command(self):
        args = build_parser().parse_args(
            ["--notebook", "playground_video.ipynb", "--port", "8770", "--no-browser"]
        )
        self.assertEqual(args.notebook, "playground_video.ipynb")
        self.assertEqual(args.port, 8770)
        self.assertTrue(args.no_browser)

        demo_args = build_parser().parse_args(normalize_demo_argv(["--demo.signal_lab", "--no-browser"]))
        self.assertEqual(demo_args.demo, "signal_lab")
        self.assertTrue(demo_args.no_browser)

        listed = list_demo_notebooks()
        self.assertIn("quickstart", {item["name"] for item in listed})
        self.assertIn("motion_demo", {item["name"] for item in listed})
        self.assertIn("rich_report", {item["name"] for item in listed})

    def test_cli_rejects_demo_conflicts_and_missing_demo_deps(self):
        with self.assertRaises(SystemExit):
            main(["--demo", "quickstart", "--notebook", "analysis.ipynb", "--no-browser"])

        with mock.patch(
            "ipynb_viewer.cli.ensure_demo_dependencies",
            side_effect=MissingDemoDependenciesError(["nbclient"]),
        ):
            with self.assertRaises(SystemExit):
                main(["--demo", "quickstart", "--no-browser"])

    def test_packaged_demo_notebooks_can_be_copied_to_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = prepare_demo_run("quickstart", base_root=root)

            self.assertEqual(run.demo, "quickstart")
            self.assertTrue(run.path.exists())
            self.assertEqual(run.root.parent.name, "demo_runs")
            self.assertIn(".notebook_viewer_cache", run.root.parts)

            payload = json.loads(run.path.read_text(encoding="utf-8"))
            self.assertEqual(payload["nbformat"], 4)
            self.assertGreater(len(payload["cells"]), 1)

            with self.assertRaises(Exception):
                prepare_demo_run("../quickstart", base_root=root)

    def test_demo_status_endpoint_reports_registered_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notebook = write_notebook(root, "demo.ipynb", [{"cell_type": "markdown", "source": "# Demo"}])
            run = DemoRun(run_id="demo-test", demo="quickstart", root=root, notebook=notebook.name, path=notebook)
            register_demo_status(run, status="running", executed=1, total=3)
            app = viewer.create_app(root=root, default_notebook=notebook.name, demo_run_id=run.run_id)
            client = app.test_client()

            response = client.get("/api/demo-status")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["data"]["runId"], "demo-test")
            self.assertEqual(response.json["data"]["executed"], 1)

    def test_demo_execution_saves_after_each_cell_with_fake_client(self):
        class FakeNbFormat:
            @staticmethod
            def read(path, as_version):
                return json.loads(Path(path).read_text(encoding="utf-8"))

            @staticmethod
            def write(notebook, handle):
                json.dump(notebook, handle)

        class FakeClient:
            def __init__(self, notebook, **kwargs):
                self.notebook = notebook

            @contextlib.contextmanager
            def setup_kernel(self):
                yield

            def execute_cell(self, cell, index):
                cell["execution_count"] = index + 1
                cell["outputs"] = [{"output_type": "stream", "name": "stdout", "text": f"cell {index}\n"}]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_notebook(
                root,
                "live.ipynb",
                [
                    {"cell_type": "markdown", "source": "# Live"},
                    {"cell_type": "code", "source": "print('a')", "outputs": [{"old": "output"}]},
                    {"cell_type": "code", "source": "print('b')", "outputs": []},
                ],
            )
            run = DemoRun(run_id="live-test", demo="quickstart", root=root, notebook=path.name, path=path)
            register_demo_status(run, status="pending", executed=0, total=0)

            execute_demo_notebook(run, dependency_loader=lambda: (FakeNbFormat, FakeClient))

            executed = json.loads(path.read_text(encoding="utf-8"))
            status = get_demo_status(run.run_id)
            self.assertEqual(status["status"], "complete")
            self.assertEqual(status["executed"], 2)
            self.assertEqual(executed["cells"][1]["execution_count"], 2)
            self.assertEqual(executed["cells"][1]["outputs"][0]["text"], "cell 1\n")
            self.assertNotIn("old", json.dumps(executed))

    def test_section_cache_invalidates_by_mtime_and_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_notebook(
                root,
                "cache.ipynb",
                [
                    {"cell_type": "markdown", "source": "# One"},
                    {"cell_type": "code", "source": "1", "outputs": []},
                ],
            )
            store = viewer.NotebookStore(root, default_notebook="cache.ipynb", max_section_cache_entries=3)

            first = store.section_payload("cache.ipynb", 0)
            second = store.section_payload("cache.ipynb", 0)
            self.assertIs(first, second)

            write_notebook(
                root,
                "cache.ipynb",
                [
                    {"cell_type": "markdown", "source": "# Two"},
                    {"cell_type": "code", "source": "22", "outputs": []},
                ],
            )
            path.touch()
            third = store.section_payload("cache.ipynb", 0)

            self.assertIsNot(first, third)
            self.assertEqual(third["section"]["title"], "Two")

    def test_outline_and_section_json_do_not_embed_base64_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_payload = base64.b64encode(PNG_BYTES).decode("ascii")
            write_notebook(
                root,
                "media.ipynb",
                [
                    {"cell_type": "markdown", "source": "# Media"},
                    {
                        "cell_type": "code",
                        "source": "display(image)",
                        "outputs": [{"output_type": "display_data", "data": {"image/png": image_payload}}],
                    },
                ],
            )
            app = viewer.create_app(root=root, default_notebook="media.ipynb")
            client = app.test_client()

            notebook = client.get("/api/notebook?path=media.ipynb")
            section = client.get("/api/section?path=media.ipynb&section=0")

            self.assertNotIn(image_payload, notebook.get_data(as_text=True))
            self.assertNotIn(image_payload, section.get_data(as_text=True))
            self.assertIn("assetUrl", section.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
