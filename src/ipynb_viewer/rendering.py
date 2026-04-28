from __future__ import annotations

import base64
import html
import io
import mimetypes
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

import bleach
import markdown
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

from .config import TEXT_OUTPUT_LIMIT

try:
    from bleach.css_sanitizer import CSSSanitizer
except Exception:  # pragma: no cover - bleach keeps this optional.
    CSSSanitizer = None  # type: ignore[assignment]

try:
    from PIL import Image
except Exception:  # pragma: no cover - pillow is a project dependency, but keep import tolerant.
    Image = None  # type: ignore[assignment]


HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
VIDEO_DATA_RE = re.compile(
    r"data:(video/(?:mp4|webm|ogg|quicktime|x-m4v|[^;\"']+));base64,([^\"']+)",
    re.IGNORECASE | re.DOTALL,
)
ASSET_ID_RE = re.compile(r"^[a-f0-9]{32,64}$")
CODE_FORMATTER = HtmlFormatter(nowrap=True)

ALLOWED_TAGS = sorted(
    set(bleach.sanitizer.ALLOWED_TAGS)
    | {
        "article",
        "aside",
        "br",
        "caption",
        "code",
        "col",
        "colgroup",
        "details",
        "div",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "img",
        "kbd",
        "li",
        "mark",
        "ol",
        "p",
        "pre",
        "samp",
        "section",
        "small",
        "source",
        "span",
        "strong",
        "sub",
        "summary",
        "sup",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
        "video",
    }
)
ALLOWED_ATTRS = {
    "*": ["class", "title", "style"],
    "a": ["href", "name", "rel", "target", "title"],
    "col": ["span", "style"],
    "colgroup": ["span", "style"],
    "img": ["alt", "height", "loading", "src", "title", "width"],
    "td": ["align", "colspan", "rowspan", "style"],
    "th": ["align", "colspan", "rowspan", "style"],
    "video": ["controls", "height", "loop", "muted", "poster", "preload", "src", "width"],
    "source": ["src", "type"],
}
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]
CSS_SANITIZER = (
    CSSSanitizer(
        allowed_css_properties=[
            "background-color",
            "border",
            "border-collapse",
            "border-color",
            "border-style",
            "border-width",
            "color",
            "display",
            "font-style",
            "font-weight",
            "height",
            "margin",
            "max-width",
            "padding",
            "text-align",
            "vertical-align",
            "white-space",
            "width",
        ]
    )
    if CSSSanitizer is not None
    else None
)
CLEANER = bleach.Cleaner(
    tags=ALLOWED_TAGS,
    attributes=ALLOWED_ATTRS,
    protocols=ALLOWED_PROTOCOLS,
    strip=True,
    css_sanitizer=CSS_SANITIZER,
)


def source_text(source: Any) -> str:
    if source is None:
        return ""
    if isinstance(source, str):
        return source
    if isinstance(source, list):
        return "".join(str(part) for part in source)
    return str(source)


def compact_text(text: str, limit: int = TEXT_OUTPUT_LIMIT) -> Dict[str, Any]:
    if len(text) <= limit:
        return {"text": text, "truncated": False}
    return {"text": text[:limit] + "\n\n[output truncated]", "truncated": True}


def clean_html(raw_html: str) -> str:
    return CLEANER.clean(raw_html or "")


def markdown_to_html(text: str) -> str:
    rendered = markdown.markdown(
        text,
        extensions=["fenced_code", "tables", "sane_lists"],
        output_format="html5",
    )
    return clean_html(rendered)


def code_line_count(source: str) -> int:
    if not source:
        return 0
    return len(source.splitlines())


def notebook_code_language(metadata: Dict[str, Any]) -> Dict[str, str]:
    language_info = metadata.get("language_info") if isinstance(metadata, dict) else None
    kernelspec = metadata.get("kernelspec") if isinstance(metadata, dict) else None
    candidates = []
    if isinstance(language_info, dict):
        candidates.extend([language_info.get("pygments_lexer"), language_info.get("name")])
    if isinstance(kernelspec, dict):
        candidates.extend([kernelspec.get("language"), kernelspec.get("name")])
    if not any(candidates):
        return {"language": "python", "languageLabel": "Python"}

    for candidate in candidates:
        language = source_text(candidate).strip()
        if not language:
            continue
        resolved = _resolve_code_language(language)
        if resolved["language"] != "text":
            return resolved
    return {"language": "text", "languageLabel": "Code"}


def highlight_code(source: str, language: str) -> str:
    try:
        lexer = get_lexer_by_name(language or "text", stripall=False)
    except ClassNotFound:
        lexer = TextLexer(stripall=False)
    return highlight(source, lexer, CODE_FORMATTER)


def _resolve_code_language(language: str) -> Dict[str, str]:
    normalized = language.strip().lower()
    if normalized in {"ipython", "ipython2", "ipython3", "python", "python2", "python3", "py"}:
        return {"language": "python", "languageLabel": "Python"}
    try:
        lexer = get_lexer_by_name(normalized)
    except ClassNotFound:
        return {"language": "text", "languageLabel": "Code"}
    alias = lexer.aliases[0] if lexer.aliases else normalized
    label = lexer.name.strip() or "Code"
    return {"language": alias, "languageLabel": label}


def heading_title(raw: str) -> str:
    stripped = re.sub(r"[`*_~]", "", raw).strip()
    stripped = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)
    return html.unescape(stripped) or "Untitled"


def iter_markdown_headings(source: str) -> Iterable[Tuple[int, str]]:
    for line in source.splitlines():
        match = HEADING_RE.match(line.strip())
        if match:
            yield len(match.group(1)), heading_title(match.group(2))


def extract_video_data_url(raw_html: str) -> Optional[Tuple[str, str]]:
    match = VIDEO_DATA_RE.search(html.unescape(raw_html or ""))
    if not match:
        return None
    return match.group(1).lower(), re.sub(r"\s+", "", match.group(2))


def decode_base64(value: Any) -> bytes:
    payload = re.sub(r"\s+", "", source_text(value))
    return base64.b64decode(payload.encode("ascii"), validate=False)


def mime_extension(mime: str) -> str:
    explicit = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/svg+xml": ".svg",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/ogg": ".ogv",
        "video/quicktime": ".mov",
        "video/x-m4v": ".m4v",
    }
    return explicit.get(mime, mimetypes.guess_extension(mime) or ".bin")


def infer_mime(path: Path) -> str:
    if path.suffix == ".svg":
        return "image/svg+xml"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def image_dimensions(mime: str, data: bytes) -> Dict[str, int]:
    if Image is None or not mime.startswith("image/") or mime == "image/svg+xml":
        return {}
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
        return {"width": int(width), "height": int(height)}
    except Exception:
        return {}
