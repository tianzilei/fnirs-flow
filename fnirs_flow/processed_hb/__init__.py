"""Vendor-processed haemoglobin analysis branch.

This branch deliberately starts from delivered HbO/HbR exports.  It never
claims to perform raw-intensity, optical-density, MBLL, short-channel, or
cortical-specific preprocessing.
"""

from .artifacts import (
    ProcessedHbArtifactMask,
    detect_processed_hb_artifacts,
    read_processed_hb_artifact_mask,
)
from .conversion_audit import validate_txt_to_snirf_roundtrip_audit
from .derivatives import freeze_processed_hb_feature_artifacts, write_processed_hb_ml_derivatives
from .io import ProcessedHbData, ProcessedHbParseError, read_vendor_processed_hb
from .manifest import ChannelAnnotationTable, build_processed_hb_manifest, join_channel_annotation_table
from .ml import nested_grouped_regression, validate_information_boundary
from .vas import run_continuous_vas_models, write_continuous_vas_derivatives
from .windows import (
    FrozenWindow,
    FrozenWindowSet,
    aggregate_window_modality_availability,
    evaluate_processed_hb_window_qc,
    extract_processed_hb_channel_window_features,
    ingest_frozen_window_set,
    processed_hb_feature_dictionary,
)

__all__ = [
    "ProcessedHbData",
    "ProcessedHbParseError",
    "read_vendor_processed_hb",
    "ProcessedHbArtifactMask",
    "detect_processed_hb_artifacts",
    "read_processed_hb_artifact_mask",
    "validate_txt_to_snirf_roundtrip_audit",
    "FrozenWindow",
    "FrozenWindowSet",
    "ingest_frozen_window_set",
    "evaluate_processed_hb_window_qc",
    "aggregate_window_modality_availability",
    "extract_processed_hb_channel_window_features",
    "processed_hb_feature_dictionary",
    "ChannelAnnotationTable",
    "build_processed_hb_manifest",
    "join_channel_annotation_table",
    "write_processed_hb_ml_derivatives",
    "freeze_processed_hb_feature_artifacts",
    "nested_grouped_regression",
    "validate_information_boundary",
    "run_continuous_vas_models",
    "write_continuous_vas_derivatives",
]
