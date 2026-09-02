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


def ingest_frozen_window_set_handler(context):
    from fnirs_flow.processed_hb import ingest_frozen_window_set

    p = {k: v for k, v in context.parameters.items() if not k.startswith("_")}
    config = p.get("config") or p.get("path") or context.raw
    return ingest_frozen_window_set(config)


def join_channel_annotation_table_handler(context):
    from fnirs_flow.processed_hb import join_channel_annotation_table

    p = {k: v for k, v in context.parameters.items() if not k.startswith("_")}
    return join_channel_annotation_table(
        p.get("path") or p.get("mapping") or context.raw,
        p.get("channels", []),
        expected_channel_count=p.get("expected_channel_count"),
    )


def evaluate_processed_hb_window_qc_handler(context):
    from fnirs_flow.processed_hb import evaluate_processed_hb_window_qc

    p = {k: v for k, v in context.parameters.items() if not k.startswith("_")}
    raw = _require_payload(context, "evaluate_processed_hb_window_qc")
    return evaluate_processed_hb_window_qc(
        raw,
        p.get("windows"),
        p.get("channel_annotations"),
        p.get("artifact_mask"),
        min_valid_sample_fraction=float(p.get("min_valid_sample_fraction", 0.8)),
        max_artifact_duration_s=float(p.get("max_artifact_duration_s", 10)),
        qc_policy_id=str(p.get("qc_policy_id", "processed_hb_window_qc_v1")),
        qc_policy_version=str(p.get("qc_policy_version", "1")),
        input_sha256=str(p.get("input_sha256", "")),
        artifact_mask_sha256=str(p.get("artifact_mask_sha256", "")),
    )


def aggregate_window_modality_availability_handler(context):
    from fnirs_flow.processed_hb import aggregate_window_modality_availability

    p = {k: v for k, v in context.parameters.items() if not k.startswith("_")}
    return aggregate_window_modality_availability(
        _require_payload(context, "aggregate_window_modality_availability"),
        min_valid_channel_fraction=float(p.get("min_valid_channel_fraction", 0.5)),
    )


def extract_processed_hb_channel_window_features_handler(context):
    from fnirs_flow.processed_hb import extract_processed_hb_channel_window_features

    p = {k: v for k, v in context.parameters.items() if not k.startswith("_")}
    raw = _require_payload(context, "extract_processed_hb_channel_window_features")
    return extract_processed_hb_channel_window_features(
        raw,
        p.get("qc_rows", []),
        p.get("windows"),
        channel_annotations=p.get("channel_annotations"),
        artifact_mask=p.get("artifact_mask"),
        feature_names=p.get("feature_names"),
        sd_ddof=int(p.get("sd_ddof", 1)),
        input_sha256=str(p.get("input_sha256", "")),
        artifact_mask_sha256=str(p.get("artifact_mask_sha256", "")),
    )


def freeze_processed_hb_feature_artifacts_handler(context):
    from fnirs_flow.processed_hb import freeze_processed_hb_feature_artifacts

    p = {k: v for k, v in context.parameters.items() if not k.startswith("_")}
    return freeze_processed_hb_feature_artifacts(
        p.get("outdir") or context.raw, **{k: v for k, v in p.items() if k != "outdir"}
    )


def write_processed_hb_ml_derivatives_handler(context):
    from fnirs_flow.processed_hb import write_processed_hb_ml_derivatives

    p = {k: v for k, v in context.parameters.items() if not k.startswith("_")}
    return write_processed_hb_ml_derivatives(
        p.get("outdir") or context.raw, **{k: v for k, v in p.items() if k != "outdir"}
    )


def nested_grouped_regression_handler(context):
    from fnirs_flow.processed_hb import nested_grouped_regression

    p = {k: v for k, v in context.parameters.items() if not k.startswith("_")}
    raw = context.raw or {}
    X = p.get("X", raw.get("X") if isinstance(raw, dict) else None)
    y = p.get("y", raw.get("y") if isinstance(raw, dict) else None)
    groups = p.get("groups", raw.get("groups") if isinstance(raw, dict) else None)
    return nested_grouped_regression(
        X,
        y,
        groups,
        target_mask=p.get("target_mask"),
        alphas=p.get("alphas", (1e-3, 1e-2, 1e-1, 1.0)),
        inner_folds=int(p.get("inner_folds", 5)),
        random_state=p.get("random_state"),
        modality_groups=p.get("modality_groups"),
        pca_components=p.get("pca_components"),
        pca_variance=p.get("pca_variance"),
        feature_selection_k=p.get("feature_selection_k"),
    )


def validate_information_boundary_handler(context):
    from fnirs_flow.processed_hb import validate_information_boundary

    p = {k: v for k, v in context.parameters.items() if not k.startswith("_")}
    return validate_information_boundary(
        p.get("feature_columns", context.raw or []),
        forbidden=p.get("forbidden", []),
        future_columns=p.get("future_columns", []),
        task=str(p.get("task", "generic")),
        prediction_time=p.get("prediction_time"),
    )


def run_continuous_vas_models_handler(context):
    from fnirs_flow.processed_hb import run_continuous_vas_models

    p = {k: v for k, v in context.parameters.items() if not k.startswith("_")}
    raw = context.raw if isinstance(context.raw, dict) else {}
    return run_continuous_vas_models(**{**raw, **p})
