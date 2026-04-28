from __future__ import annotations

import argparse
import webbrowser
from threading import Timer

from .app import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smooth local viewer for saved Jupyter notebooks")
    parser.add_argument("--root", default=".", help="Root directory that notebooks must stay inside")
    parser.add_argument("--notebook", default="", help="Notebook path relative to --root")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--no-browser", action="store_true")
    return parser


def open_browser(port: int) -> None:
    webbrowser.open(f"http://localhost:{port}")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    app = create_app(root=args.root, default_notebook=args.notebook or None)
    print(f"\n  notebook-viewer -> http://localhost:{args.port}\n")
    if not args.no_browser:
        Timer(1.0, open_browser, args=[args.port]).start()
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
