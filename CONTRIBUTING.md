# Contributing

Thanks for helping improve `ipynb-viewer`.

## Development Setup

Create a virtual environment with your preferred tool, then install the package
in editable mode:

```bash
python -m pip install -e .
python -m pip install build twine trove-classifiers
```

Run the checks before opening a pull request:

```bash
python -m unittest discover -s tests
python -m compileall src
python -m build
python -m twine check dist/*
python -m trove_classifiers check pyproject.toml
```

## Pull Requests

- Keep changes focused and easy to review.
- Add or update tests for behavior changes.
- Update `README.md` or `CHANGELOG.md` when user-facing behavior changes.
- Do not commit generated caches, virtual environments, or local notebooks.

## Design Notes

`ipynb-viewer` intentionally stays lightweight:

- Flask app, vanilla JavaScript, no frontend build step.
- Saved notebooks only; no code execution.
- Large output media should stay out of main JSON responses.
- HTML from notebooks should remain sanitized before rendering.
