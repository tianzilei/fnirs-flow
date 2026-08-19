"""Smoke tests for fnirs-flow package structure."""

from __future__ import annotations

import importlib


def test_version_importable():
    import fnirs_flow

    assert hasattr(fnirs_flow, "__version__")
    assert fnirs_flow.__version__ != ""


def test_subpackages_importable():
    subpackages = (
        "flow",
        "validation",
        "compiler",
        "execution",
        "registry",
        "exporters",
        "history",
        "security",
        "dependencies",
    )
    for subpackage in subpackages:
        module = importlib.import_module(f"fnirs_flow.{subpackage}")
        assert module.__name__ == f"fnirs_flow.{subpackage}"
