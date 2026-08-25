"""Runtime operation handlers for the processed-Hb branch."""

from __future__ import annotations


def _require_payload(context, operation: str):
    if context.raw is None:
        raise ValueError(f"{operation} requires its typed upstream payload")
    return context.raw


def frozen_manifest_discovery_handler(context):
    """Project executor marker; discovery itself is driven by the frozen-manifest CLI/API."""
    return _require_payload(context, "frozen_manifest_discovery")


def read_vendor_processed_hb_handler(context):
    from fnirs_flow.adapters.vendor_processed_hb import parse_vendor_processed_hb

    parameters = {key: value for key, value in context.parameters.items() if not key.startswith("_")}
    path = parameters.pop("path", None) or parameters.pop("runtime_signal_path", None)
    if path is None and context.raw is not None:
        path = getattr(context.raw, "runtime_signal_path", context.raw)
        parameters.setdefault("uri", getattr(context.raw, "signal_uri", ""))
    if not path:
        raise ValueError("read_vendor_processed_hb requires a runtime signal path")
    if parameters.get("encoding") == "auto":
        parameters["encoding"] = None
    recording, qc = parse_vendor_processed_hb(path, **{k: v for k, v in parameters.items() if k in {"uri", "encoding"}})
    return {
        "recording": recording,
        "provenance": recording.provenance,
        "channel_map": recording.channels,
        "parser_qc": qc,
    }


def ingest_frozen_events_handler(context):
    return _require_payload(context, "ingest_frozen_events")


def regularize_processed_hb_time_handler(context):
    return _require_payload(context, "regularize_processed_hb_time")


def compile_processed_hb_designs_handler(context):
    return _require_payload(context, "compile_processed_hb_designs")


def fit_processed_hb_first_level_handler(context):
    return _require_payload(context, "fit_processed_hb_first_level")


def estimate_full_contrasts_handler(context):
    return _require_payload(context, "estimate_full_contrasts")


def write_processed_hb_derivatives_handler(context):
    return _require_payload(context, "write_processed_hb_derivatives")
