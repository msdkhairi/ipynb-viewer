from __future__ import annotations

from pathlib import Path

from trove_classifiers import classifiers

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only needed on Python 3.10.
    import tomli as tomllib  # type: ignore[no-redef]


def main() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    invalid = sorted(set(project.get("classifiers", [])) - classifiers)
    if invalid:
        joined = "\n".join(f"- {item}" for item in invalid)
        raise SystemExit(f"Invalid trove classifiers:\n{joined}")


if __name__ == "__main__":
    main()
