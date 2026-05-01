from __future__ import annotations

import argparse
import sys
import webbrowser
from threading import Timer

from .app import create_app
from .demos import (
    DemoError,
    ensure_demo_dependencies,
    list_demo_notebooks,
    normalize_demo_argv,
    normalize_demo_name,
    prepare_demo_run,
    start_demo_execution,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smooth local viewer for saved Jupyter notebooks")
    parser.add_argument("--root", default=".", help="Root directory that notebooks must stay inside")
    parser.add_argument("--notebook", default="", help="Notebook path relative to --root")
    parser.add_argument("--demo", default="", help="Run a packaged demo notebook by name")
    parser.add_argument("--list-demos", action="store_true", help="List packaged demo notebooks and exit")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--no-browser", action="store_true")
    return parser


def open_browser(port: int) -> None:
    webbrowser.open(f"http://localhost:{port}")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    raw_argv = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(normalize_demo_argv(raw_argv))

    if args.list_demos:
        for demo in list_demo_notebooks():
            print(f"{demo['name']}: {demo['title']} - {demo['description']}")
        return

    if args.demo and args.notebook:
        parser.error("--demo cannot be used with --notebook.")

    demo_run_id = None
    if args.demo:
        try:
            normalize_demo_name(args.demo)
            ensure_demo_dependencies()
            demo_run = prepare_demo_run(args.demo, base_root=args.root)
            start_demo_execution(demo_run)
        except DemoError as exc:
            parser.error(str(exc))
        args.root = str(demo_run.root)
        args.notebook = demo_run.notebook
        demo_run_id = demo_run.run_id

    app = create_app(root=args.root, default_notebook=args.notebook or None, demo_run_id=demo_run_id)
    print(f"\n  notebook-viewer -> http://localhost:{args.port}")
    if demo_run_id:
        print(f"  running demo -> {args.notebook}")
    print()
    if not args.no_browser:
        Timer(1.0, open_browser, args=[args.port]).start()
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
