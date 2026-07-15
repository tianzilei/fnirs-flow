"""Tests for optional scientific backend registration and detection."""

from __future__ import annotations

from fnirs_flow.adapters.backend_registry import get_registry


def test_known_backends_are_registered_even_when_optional_packages_are_missing():
    registry = get_registry()
    assert "mne_nirs" in registry.list_all()
    assert "cedalion" in registry.list_all()
    assert registry.get("cedalion") is not None
