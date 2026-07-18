"""Small SVG sanitizer for generated result previews."""

from __future__ import annotations

import re

_BLOCKED_ELEMENT_NAMES = (
    "script",
    "foreignObject",
    "iframe",
    "object",
    "embed",
    "link",
    "meta",
    "style",
    "audio",
    "video",
    "canvas",
)
_BLOCKED_ELEMENT_RE = re.compile(
    rf"<\s*({'|'.join(_BLOCKED_ELEMENT_NAMES)})\b[\s\S]*?<\s*/\s*\1\s*>",
    re.IGNORECASE,
)
_BLOCKED_SELF_CLOSING_RE = re.compile(
    rf"<\s*({'|'.join(_BLOCKED_ELEMENT_NAMES)})\b[^>]*/\s*>",
    re.IGNORECASE,
)
_EVENT_HANDLER_ATTR_RE = re.compile(r"\s+on[a-zA-Z]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'=<>`]+)")
_STYLE_ATTR_RE = re.compile(r"\s+style\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'=<>`]+)", re.IGNORECASE)
_URL_ATTR_RE = re.compile(
    r"\s+(href|xlink:href|src)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s\"'=<>`]+)",
    re.IGNORECASE,
)
_UNSAFE_ATTR_VALUE_RE = re.compile(
    r"\s+[a-zA-Z_:.-]+\s*=\s*"
    r"(?:\"[^\"]*(?:javascript:|data:|vbscript:)[^\"]*\""
    r"|'[^']*(?:javascript:|data:|vbscript:)[^']*'"
    r"|[^\s\"'=<>`]*(?:javascript:|data:|vbscript:)[^\s\"'=<>`]*)",
    re.IGNORECASE,
)


def _strip_preamble(value: str) -> str:
    without_bom = re.sub(r"^\ufeff", "", value)
    without_xml = re.sub(r"^<\?xml[\s\S]*?\?>\s*", "", without_bom, flags=re.IGNORECASE)
    return re.sub(r"<!doctype[\s\S]*?>", "", without_xml, flags=re.IGNORECASE).strip()


def _unquote_attribute_value(value: str) -> str:
    trimmed = value.strip()
    if (trimmed.startswith('"') and trimmed.endswith('"')) or (trimmed.startswith("'") and trimmed.endswith("'")):
        return trimmed[1:-1]
    return trimmed


def _sanitize_url_attr(match: re.Match[str]) -> str:
    url = _unquote_attribute_value(match.group(2)).strip().lower()
    return match.group(0) if url.startswith("#") else ""


def sanitize_svg(svg: str) -> str:
    """Return inert inline SVG markup, or an empty string for non-SVG payloads."""
    trimmed = _strip_preamble(svg)
    if not re.match(r"^<svg(?:\s|>)", trimmed, flags=re.IGNORECASE):
        return ""
    if not re.search(r"</svg>\s*$", trimmed, flags=re.IGNORECASE):
        return ""

    sanitized = _BLOCKED_ELEMENT_RE.sub("", trimmed)
    sanitized = _BLOCKED_SELF_CLOSING_RE.sub("", sanitized)
    sanitized = _EVENT_HANDLER_ATTR_RE.sub("", sanitized)
    sanitized = _STYLE_ATTR_RE.sub("", sanitized)
    sanitized = _UNSAFE_ATTR_VALUE_RE.sub("", sanitized)
    return _URL_ATTR_RE.sub(_sanitize_url_attr, sanitized)
