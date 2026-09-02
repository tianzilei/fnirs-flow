"""Shared operation contracts that do not depend on concrete handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


class OperationHandler(Protocol):
    spec: OperationSpec

    def execute(self, context: Any) -> Any: ...


@dataclass
class OperationContext:
    adapter: Any
    raw: Any
    parameters: dict[str, Any]
    service: Any = None


class CallableOperationHandler:
    def __init__(self, spec: OperationSpec, callback: Callable[[OperationContext], Any]) -> None:
        self.spec = spec
        self.callback = callback

    def execute(self, context: OperationContext) -> Any:
        return self.callback(context)


@dataclass
class OperationSpec:
    operation_id: str
    category: str = ""
    input_schemas: list[str] = field(default_factory=list)
    output_schemas: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    execution_scope: str = "run"
    supported_backends: list[str] = field(default_factory=list)
    artifact_contract: dict[str, Any] = field(default_factory=dict)
    allow_reviewed_noop: bool = False
    handler_factory: Callable[..., OperationHandler] | None = None
    backend_handler_factories: dict[str, Callable[..., OperationHandler]] = field(default_factory=dict)
    contract_variants: dict[str, dict[str, Any]] = field(default_factory=dict)

    def handler_factory_for(self, backend_id: str | None = None) -> Callable[..., OperationHandler] | None:
        if backend_id and backend_id in self.backend_handler_factories:
            return self.backend_handler_factories[backend_id]
        if backend_id and self.supported_backends and backend_id not in self.supported_backends:
            return None
        return self.handler_factory


OPERATION_ALIASES: dict[str, str] = {
    "data_import": "read_run",
    "hardware_import": "read_run",
    "bandpass_filter": "filtering",
    "hpf_lpf_filter": "filtering",
    "mbll_conversion": "beer_lambert_law",
    "signal_quality_check": "compute_qc",
    "snirf_reader": "read_run",
    "optical_density_conversion": "optical_density",
    "qc_metrics": "compute_qc",
    "sci_check": "compute_qc",
    "cv_check": "compute_qc",
    "snr_check": "compute_qc",
    "bad_channel_detection": "compute_qc",
    "tddr": "motion_correction",
    "wavelet": "motion_correction",
    "spline": "motion_correction",
    "ica": "motion_correction",
    "pca": "motion_correction",
    "bandpass": "filtering",
    "notch": "filtering",
    "lowpass": "filtering",
    "mbll": "beer_lambert_law",
    "design_matrix": "build_design_matrix",
    "contrast": "estimate_contrast",
}


def canonical_operation(operation_id: str) -> str:
    return OPERATION_ALIASES.get(operation_id, operation_id)
