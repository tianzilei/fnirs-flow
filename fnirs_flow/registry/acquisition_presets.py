"""Canonical built-in acquisition metadata shared by preset APIs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

BUILTIN_ACQUISITION_PRESETS: dict[str, dict[str, Any]] = {
    "shimadzu_omm": {
        "device_brand_model": "Shimadzu OMM",
        "data_format": "OMM",
        "wavelengths_nm": [780, 805, 830],
        "source_detector_distance_mm": None,
        "short_channel_distance_mm": None,
        "applied_voltage": [],
        "amp_gain": [],
    }
}


def get_builtin_acquisition_preset(preset_id: str) -> dict[str, Any] | None:
    """Return a defensive copy of a canonical acquisition preset."""
    preset = BUILTIN_ACQUISITION_PRESETS.get(preset_id)
    return deepcopy(preset) if preset is not None else None
