"""Fail-closed readers for text Shimadzu/NIRS-SPM layout files."""

from __future__ import annotations

import configparser
import re
from pathlib import Path
from typing import Any


class ShimadzuLayoutError(ValueError):
    """Raised when a layout format cannot be identified and parsed safely."""


def _parse_wavelengths(sections: dict[str, dict[str, str]]) -> list[float]:
    """Extract explicitly labelled optical wavelengths from text metadata."""
    candidates: list[float] = []
    for values in sections.values():
        for key, value in values.items():
            normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
            if normalized not in {"wavelength", "wavelengthnm", "wavelengths", "wavelengthsnm"}:
                continue
            parsed = [float(token) for token in re.findall(r"\d+(?:\.\d+)?", value)]
            if not parsed or any(item < 600 or item > 1000 for item in parsed):
                raise ShimadzuLayoutError("wavelength metadata must contain values between 600 and 1000 nm")
            candidates.extend(parsed)
    return list(dict.fromkeys(candidates))


def read_shimadzu_layout(path: str | Path) -> dict[str, Any]:
    """Read a validated text ``.inf``/``.ini`` layout.

    Proprietary binary ``.inf`` variants are intentionally rejected until a
    versioned format parser and equivalence fixtures are available. Returning
    guessed channel geometry or wavelengths would create false provenance.
    """

    source = Path(path).expanduser().resolve()
    raw = source.read_bytes()
    if not raw:
        raise ShimadzuLayoutError("Shimadzu layout is empty")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ShimadzuLayoutError("unsupported binary Shimadzu layout; a validated text INI is required") from exc
    if "\x00" in text:
        raise ShimadzuLayoutError("unsupported binary Shimadzu layout; a validated text INI is required")

    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise ShimadzuLayoutError(f"invalid Shimadzu text layout: {exc}") from exc
    if not parser.sections():
        raise ShimadzuLayoutError("invalid Shimadzu text layout: no INI sections found")

    sections = {section: dict(parser.items(section)) for section in parser.sections()}
    wavelengths = _parse_wavelengths(sections)
    return {
        "path": str(source),
        "format": "shimadzu_text_layout_v1",
        "file_extension": source.suffix.lower(),
        "is_binary": False,
        "layout_name": source.stem,
        "sections": sections,
        "channels": [],
        "wavelengths_nm": wavelengths,
        "metadata_status": "parsed" if wavelengths else "parsed_without_wavelengths",
    }


def read_nirs_spm_ini(path: str | Path) -> dict[str, Any]:
    """Compatibility alias for validated text NIRS-SPM layout files."""

    return read_shimadzu_layout(path)
