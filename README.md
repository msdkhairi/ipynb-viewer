# ipynb-viewer

`ipynb-viewer` is a lightweight local Flask app for reading saved Jupyter
notebooks as a smooth document. It builds an outline from markdown headings,
shows notebook outputs first, keeps code cells collapsed by default, and serves
large images or videos through lazy asset URLs instead of embedding base64 media
inside the main UI JSON.

The viewer reads saved `.ipynb` files only. It does not execute notebook code.

## Install

From this checkout:

```bash
cd /home/workspace/UnivCollabSFU24/ipynb-viewer
python -m pip install -e .
```

After installation, the command is:

```bash
notebook-viewer --help
```

## Start And Stop

Start the viewer on `http://localhost:8770`:

```bash
notebook-viewer --root /home/workspace/UnivCollabSFU24 --notebook playground_video.ipynb --port 8770 --no-browser
```

Stop a foreground server with `Ctrl-C`.

For a background server:

```bash
notebook-viewer --root /home/workspace/UnivCollabSFU24 --notebook playground_video.ipynb --port 8770 --no-browser > notebook-viewer.log 2>&1 &
echo $! > notebook-viewer.pid
```

Stop that background server:

```bash
kill "$(cat notebook-viewer.pid)"
```

## CLI

```bash
notebook-viewer --root . --notebook playground_video.ipynb --port 8770 --no-browser
```

Options:

- `--root`: directory that readable notebooks must stay inside
- `--notebook`: notebook path relative to `--root`
- `--host`: bind host, default `0.0.0.0`
- `--port`: bind port, default `8770`
- `--no-browser`: do not open a browser automatically

## Behavior

- Notebook access is restricted to the configured `--root`.
- HTML outputs are sanitized with Bleach.
- Code cells are syntax-highlighted with Pygments and still include the raw
  source in section API responses.
- Images and videos are decoded to `.notebook_viewer_cache/` and streamed from
  `/api/asset/<asset_id>`.
- Notebook and section payloads avoid embedding large base64 media.
- Section JSON is cached in memory and invalidated when notebook mtime or size
  changes.

## Development

Run tests from this package directory:

```bash
python -m unittest discover -s tests
python -m compileall src
```

Build the package:

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
```

## Publish

Create PyPI and TestPyPI API tokens first. When Twine asks for credentials, use
`__token__` as the username and paste the token as the password.

Upload to TestPyPI:

```bash
python -m twine upload --repository testpypi dist/*
```

Install from TestPyPI:

```bash
python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple ipynb-viewer
```

Upload to PyPI:

```bash
python -m twine upload dist/*
```

The package name `ipynb-viewer` is only guaranteed if PyPI accepts the upload.
