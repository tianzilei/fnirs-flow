"""Regression checks for the real task-GLM demo flow."""

from __future__ import annotations

import json
from pathlib import Path

from fnirs_flow.validation.api import validate_flow


def _load_demo_flow() -> dict:
    path = Path(__file__).resolve().parents[1] / "configs" / "demo_task_glm_real.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_demo_task_glm_real_is_valid():
    result = validate_flow(_load_demo_flow())

    assert result.is_valid


def test_qc_metrics_consumes_optical_density():
    flow = _load_demo_flow()
    nodes = {node["id"]: node for node in flow["nodes"]}
    qc_ports = {port["name"]: port for port in nodes["qc_metrics"]["ports"]}
    qc_edge = next(edge for edge in flow["edges"] if edge["target"] == "qc_metrics")

    assert qc_ports["od_data"]["schema"] == "OpticalDensityData"
    assert qc_edge["source"] == "optical_density"
    assert qc_edge["source_handle"] == "od_data"
    assert qc_edge["target_handle"] == "od_data"
