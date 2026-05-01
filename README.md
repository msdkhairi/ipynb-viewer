# ipynb-local-viewer

[![PyPI](https://img.shields.io/pypi/v/ipynb-local-viewer.svg)](https://pypi.org/project/ipynb-local-viewer/)
[![Python](https://img.shields.io/pypi/pyversions/ipynb-local-viewer.svg)](https://pypi.org/project/ipynb-local-viewer/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/msdkhairi/ipynb-viewer/actions/workflows/ci.yml/badge.svg)](https://github.com/msdkhairi/ipynb-viewer/actions/workflows/ci.yml)

A local-first reader for saved Jupyter notebooks that makes `.ipynb` files feel
like polished reports.

`ipynb-local-viewer` opens notebooks in a fast Flask-powered reading surface:
markdown headings become an outline, outputs are shown before source code, code
is collapsed behind syntax-highlighted details, rich HTML is sanitized, and
large image or video outputs are streamed lazily through local asset URLs.

In normal viewing mode it reads saved notebooks only and does not execute user
notebook code. Packaged demos can be executed explicitly with the optional
`[demo]` extra.

![ipynb-local-viewer preview](https://raw.githubusercontent.com/msdkhairi/ipynb-viewer/main/docs/assets/viewer-showcase.svg)

## Quick Start

Install the viewer:

```bash
pip install ipynb-local-viewer
```

Open a notebook on `http://localhost:8770`:

```bash
notebook-viewer --notebook analysis.ipynb --host 127.0.0.1 --port 8770
```

Restrict browsing to a project directory:

```bash
notebook-viewer --root ~/projects/my-analysis --notebook notebooks/report.ipynb --host 127.0.0.1
```

Stop a foreground server with `Ctrl-C`.

## Try The Demos

Install the optional demo stack and launch the first-run tour:

```bash
pip install "ipynb-local-viewer[demo]"
notebook-viewer --demo quickstart --host 127.0.0.1
```

The demos are bundled with the package, run offline, and are designed to show
the viewer's rendering paths without large downloads or heavy training jobs.

| Demo | Run it | What it shows |
| --- | --- | --- |
| Quickstart Tour | `notebook-viewer --demo quickstart` | Outline navigation, output-first reading, tables, charts, sanitized HTML, and collapsed source. |
| Rich Report | `notebook-viewer --demo rich_report` | A compact executive report with KPI tables, static charts, generated imagery, and HTML callouts. |
| Signal Lab | `notebook-viewer --demo signal_lab` | A deterministic NumPy/SciPy workflow with filtering, frequency analysis, and spectrograms. |
| Interactive Charts | `notebook-viewer --demo interactive_charts` | Pandas, seaborn, matplotlib, and Plotly-generated HTML with a safe fallback. |
| Visual Story | `notebook-viewer --demo visual_story` | Generated images, color fields, and SVG output served as lazy assets. |
| Motion Demo | `notebook-viewer --demo motion_demo` | A tiny packaged MP4 and generated frame strip for lazy video/image loading. |

List the demos from any installed environment:

```bash
notebook-viewer --list-demos
```

The dotted shorthand also works:

```bash
notebook-viewer --demo.rich_report
```

## Highlights

- Local reader for saved `.ipynb` files; no frontend build step.
- Markdown-derived outline with smooth section navigation.
- Output-first reading flow with collapsible, syntax-highlighted code.
- Lazy image, SVG, GIF, and video asset streaming for media-heavy notebooks.
- Sanitized markdown and notebook HTML rendering with Bleach.
- Light, dark, and device theme modes.
- Root-restricted notebook access for safer local browsing.
- Packaged live demos with deterministic scientific, media, and report outputs.

## CLI Reference

```bash
notebook-viewer [--root ROOT] [--notebook NOTEBOOK] [--demo DEMO] [--list-demos] [--host HOST] [--port PORT] [--no-browser]
```

Common options:

- `--root`: directory that readable notebooks must stay inside, default `.`
- `--notebook`: notebook path relative to `--root`
- `--demo`: copy and execute a packaged demo notebook by name
- `--demo.NAME`: shorthand for `--demo NAME`
- `--list-demos`: list packaged demos and exit
- `--host`: bind host, default `0.0.0.0`
- `--port`: bind port, default `8770`
- `--no-browser`: do not open a browser automatically

## How It Works

The server parses saved notebook JSON with the Python standard library and
caches parsed notebooks by path, mtime, and size. Markdown headings define the
outline. Selecting or scrolling to a section loads the cells for that section.

Notebook and section JSON responses avoid embedding large base64 media payloads:
image and video outputs are represented as asset descriptors and streamed from
`/api/asset/<asset_id>` when the browser needs them.

Supported output behavior:

- PNG, JPEG, GIF, SVG, and common video MIME outputs become lazy asset URLs.
- HTML video data URLs are extracted into streamed video assets.
- HTML tables and rich HTML outputs are sanitized before rendering.
- stdout, stderr, tracebacks, and unsupported widgets use readable fallback
  blocks.
- Code cells include raw source and highlighted HTML in the section API.

## API

Local API endpoints:

- `GET /api/notebooks`: list `.ipynb` files under `--root`
- `GET /api/notebook?path=...`: return outline and section metadata
- `GET /api/section?path=...&section=...`: return cells for one section
- `GET /api/asset/<asset_id>`: stream decoded media assets
- `GET /api/demo-status?run_id=...`: return live demo execution status

## Security Notes

`ipynb-local-viewer` is a local reader, not a notebook execution environment.

- It never runs user-selected notebook code in normal viewing mode.
- Demo mode runs only packaged demo notebooks and must be started explicitly.
- Notebook access is restricted to the configured `--root`.
- Markdown-rendered HTML and notebook HTML outputs are sanitized.
- Decoded media assets are served from `.notebook_viewer_cache/`.
- Demo run copies are written under `.notebook_viewer_cache/demo_runs/`.

As with any local web server, bind it only where you intend to expose it. Use
`--host 127.0.0.1` for loopback-only access.

## Development

Install locally:

```bash
python -m pip install -e ".[demo]"
```

Run checks:

```bash
python -m unittest discover -s tests
python -m compileall src
python scripts/check_classifiers.py
```

Build and validate distribution artifacts:

```bash
python -m build
python -m twine check dist/*
```

## Publishing

Releases are intended to use PyPI Trusted Publishing from GitHub Actions.

```bash
git tag v0.1.0
git push origin v0.1.0
```

Then create a GitHub release for that tag. The release workflow builds the
artifacts, validates them, and publishes with PyPI Trusted Publishing.

Manual fallback:

```bash
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

## License

`ipynb-local-viewer` is distributed under the MIT License. See [LICENSE](LICENSE).
