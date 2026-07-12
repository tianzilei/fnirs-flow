"""Shared fixtures for fnirs-flow tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = PROJECT_ROOT / ".tmp" / "pytest"
MNE_HOME = PROJECT_ROOT / ".tmp" / "mne"
TEST_TMP.mkdir(parents=True, exist_ok=True)
MNE_HOME.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("TMP", str(TEST_TMP))
os.environ.setdefault("TEMP", str(TEST_TMP))
os.environ.setdefault("TMPDIR", str(TEST_TMP))
os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(TEST_TMP))
os.environ.setdefault("_MNE_FAKE_HOME_DIR", str(MNE_HOME))
os.environ.setdefault("MNE_HOME", str(MNE_HOME))
os.environ.setdefault("MNE_DONTWRITE_HOME", "true")


@pytest.fixture
def minimal_flow_dict() -> dict:
    """Minimal valid flow dict for testing."""
    return {
        "schema_version": "0.1.0",
        "flow_id": "test-flow-001",
        "name": "Test Flow",
        "description": "A minimal test flow",
        "nodes": [
            {
                "id": "node-1",
                "type": "dataset_discovery",
                "category": "data",
                "position": {"x": 0, "y": 0},
                "config": {"dataset_id": "test-dataset"},
                "status": "ready",
                "ports": [{"name": "output", "direction": "out", "schema": "TestData", "required": True}],
            },
            {
                "id": "node-2",
                "type": "optical_density",
                "category": "preprocessing",
                "position": {"x": 200, "y": 0},
                "config": {},
                "status": "ready",
                "ports": [
                    {"name": "input", "direction": "in", "schema": "TestData", "required": True},
                    {
                        "name": "output",
                        "direction": "out",
                        "schema": "OpticalDensityData",
                        "required": True,
                    },
                ],
            },
        ],
        "edges": [
            {
                "id": "edge-1",
                "source": "node-1",
                "target": "node-2",
                "source_handle": "output",
                "target_handle": "input",
            }
        ],
        "adapter_registry": [],
        "metadata": {
            "created_at": "2026-01-01T00:00:00Z",
            "modified_at": "2026-01-01T00:00:00Z",
        },
    }
