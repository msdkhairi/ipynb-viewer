# ipynb-local-viewer

[![PyPI](https://img.shields.io/pypi/v/ipynb-local-viewer.svg)](https://pypi.org/project/ipynb-local-viewer/)
[![Python](https://img.shields.io/pypi/pyversions/ipynb-local-viewer.svg)](https://pypi.org/project/ipynb-local-viewer/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/msdkhairi/ipynb-viewer/actions/workflows/ci.yml/badge.svg)](https://github.com/msdkhairi/ipynb-viewer/actions/workflows/ci.yml)

A smooth, local-first reader for saved Jupyter notebooks.

`ipynb-local-viewer` turns an `.ipynb` file into a fast reading surface: markdown
headings become an outline, outputs are shown first, code is collapsed behind
syntax-highlighted expandable blocks, and large images or videos are loaded
through lazy streamed asset URLs instead of being embedded into the main page
payload.

It reads saved notebooks only. It does not execute code.

## Features

- Markdown-derived outline with smooth section navigation.
- Lazy image and video output loading for media-heavy notebooks.
- Collapsed code cells with Pygments syntax highlighting.
- Safe sanitized HTML output rendering with Bleach.
- Light, dark, and device theme modes.
- Local Flask server with no frontend build step.
- Root-restricted notebook access for safer local browsing.
- Small decoded media cache for faster repeat reads.

## Install

```bash
python -m pip install ipynb-local-viewer
```

For local development from a checkout:

```bash
python -m pip install -e .
```

## Quick Start

Open a notebook on `http://localhost:8770`:

```bash
notebook-viewer --notebook analysis.ipynb --port 8770
```

Restrict the viewer to a specific project directory:

```bash
notebook-viewer --root ~/projects/my-analysis --notebook notebooks/report.ipynb --port 8770
```

Start without opening a browser:

```bash
notebook-viewer --root . --notebook analysis.ipynb --port 8770 --no-browser
```

Stop a foreground server with `Ctrl-C`.

## CLI

```bash
notebook-viewer [--root ROOT] [--notebook NOTEBOOK] [--host HOST] [--port PORT] [--no-browser]
```

Options:

- `--root`: directory that readable notebooks must stay inside, default `.`
- `--notebook`: notebook path relative to `--root`
- `--host`: bind host, default `0.0.0.0`
- `--port`: bind port, default `8770`
- `--no-browser`: do not open a browser automatically

## How It Works

The viewer parses saved notebook JSON with the Python standard library and
caches parsed notebooks by path, mtime, and size. Markdown headings define the
outline. Selecting or scrolling to a section loads the cells for that section,
while image and video outputs are represented as asset descriptors and streamed
separately from `/api/asset/<asset_id>`.

Supported output behavior:

- PNG, JPEG, GIF, SVG, and common video MIME outputs become lazy asset URLs.
- HTML video data URLs are extracted into streamed video assets.
- HTML tables and rich HTML outputs are sanitized before rendering.
- stdout, stderr, tracebacks, and unsupported widgets use readable fallback
  blocks.
- Code cells include raw source and highlighted HTML in the section API.

## API

The local server exposes a small JSON/asset API:

- `GET /api/notebooks`: list `.ipynb` files under `--root`
- `GET /api/notebook?path=...`: return outline and section metadata
- `GET /api/section?path=...&section=...`: return cells for one section
- `GET /api/asset/<asset_id>`: stream decoded media assets

Notebook and section JSON responses avoid embedding large base64 media payloads.

## Security Notes

`ipynb-local-viewer` is a local reader, not a notebook execution environment.

- It never runs notebook code.
- It restricts notebook access to the configured `--root`.
- It sanitizes markdown-rendered HTML and notebook HTML outputs.
- It serves decoded media assets from `.notebook_viewer_cache/`.

As with any local web server, bind it only where you intend to expose it. The
default host is `0.0.0.0`; use `--host 127.0.0.1` for loopback-only access.

## Development

Install development tools and run the test suite:

```bash
python -m pip install -e .
python -m pip install build twine trove-classifiers tomli
python -m unittest discover -s tests
python -m compileall src
```

Build and validate distribution artifacts:

```bash
python -m build
python -m twine check dist/*
python scripts/check_classifiers.py
```

## Publishing

Releases are intended to use PyPI Trusted Publishing from GitHub Actions.

One-time PyPI setup:

1. Log into the PyPI account `masoudka`.
2. Create or select the PyPI project `ipynb-local-viewer`.
3. Add a pending trusted publisher for:
   - Owner: `msdkhairi`
   - Repository: `ipynb-viewer`
   - Workflow: `release.yml`
   - Environment: `pypi`

`Owner` is the GitHub repository owner, not the PyPI username. The GitHub
repository can remain `ipynb-viewer` even though the PyPI distribution name is
`ipynb-local-viewer`.

Release flow:

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
