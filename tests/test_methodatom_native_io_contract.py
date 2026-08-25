"""Regression checks for MethodAtom/native backend routing.

The literature library and the hand-authored native templates must not drift
into different numerical implementations for the same fNIRS operation.
"""

from __future__ import annotations

from fnirs_flow.execution.operations import OperationContext, create_default_registry
from fnirs_flow.registry.methodatom_library import load_literature_method_atom_templates


class _NativeAdapter:
    backend_id = "mne_nirs"

    def __init__(self):
        self.calls = []

    def read_run(self, path):
        self.calls.append(("read_run", path))
        return "raw"

    def apply_filter(self, raw, **kwargs):
        self.calls.append(("apply_filter", raw, kwargs))
        return "filtered"

    def to_haemoglobin(self, raw, **kwargs):
        self.calls.append(("to_haemoglobin", raw, kwargs))
        return "hb"

    def compute_qc(self, raw, **kwargs):
        self.calls.append(("compute_qc", raw, kwargs))
        return {"native": True}

    def apply_short_channel_regression(self, raw, **kwargs):
        self.calls.append(("apply_short_channel_regression", raw, kwargs))
        return "scr"


def _execute(operation, adapter, raw=None, **parameters):
    return create_default_registry().execute(
        operation,
        OperationContext(adapter=adapter, raw=raw, parameters=parameters),
    )


def test_literature_core_atoms_use_native_adapter_routes():
    operations = {
        str(template.operation or template.atom_type)
        for template in load_literature_method_atom_templates()
    }
    assert {
        "data_import",
        "hardware_import",
        "bandpass_filter",
        "mbll_conversion",
        "signal_quality_check",
        "short_channel_regression",
    } <= operations

    registry = create_default_registry()
    for operation in (
        "data_import",
        "hardware_import",
        "bandpass_filter",
        "mbll_conversion",
        "signal_quality_check",
        "short_channel_regression",
    ):
        spec = registry.get(operation)
        assert spec is not None
        assert spec.handler_factory_for("mne_nirs").__module__.endswith("builtin_handlers")


def test_literature_aliases_call_native_methods_with_unit_normalization():
    adapter = _NativeAdapter()
    assert _execute("data_import", adapter, path="recording.snirf") == "raw"
    assert _execute("bandpass_filter", adapter, raw="od", l_freq=0.01, h_freq=0.2) == "filtered"
    assert _execute("mbll_conversion", adapter, raw="od", ppf=6.0) == "hb"
    assert _execute("signal_quality_check", adapter, raw="od") == {"native": True}
    assert _execute(
        "short_channel_regression",
        adapter,
        raw="hb",
        short_channel_distance_mm=8,
    ) == "scr"

    names = [call[0] for call in adapter.calls]
    assert names == [
        "read_run",
        "apply_filter",
        "to_haemoglobin",
        "compute_qc",
        "apply_short_channel_regression",
    ]
    short_channel_call = adapter.calls[-1]
    assert short_channel_call[2]["short_channel_threshold"] == 0.008
