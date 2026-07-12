"""Smoke tests for fnirs-flow package structure."""

from __future__ import annotations


def test_version_importable():
    import fnirs_flow

    assert hasattr(fnirs_flow, "__version__")
    assert fnirs_flow.__version__ == "1.0.2"


def test_subpackages_importable():
    pass
