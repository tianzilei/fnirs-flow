"""Typed contracts for vendor processed haemoglobin recordings.

The processed-Hb branch is deliberately separate from the raw intensity/BIDS
models.  These small, dependency-light models are also useful to callers that
only want to validate a frozen manifest without importing MNE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field


class ProcessedHbRun(BaseModel):
    model_config = {"extra": "forbid"}
    linked_record_id: str
    fnirs_record_id: str
    record_pair_id: str
    signal_uri: str
    runtime_signal_path: str = Field(default="", exclude=True)
    input_sha256: str = ""
    declared_channel_count: int | None = None
    sync_grade: str = ""
    event_primary_eligible: bool = False
    lag_primary_eligible: bool = False
    observed_coverage: str | float | None = None
    analysis_included: bool = False
    frozen_exclusion_reason: str | None = None
    event_table_uri: str = ""
    data_branch: Literal["vendor_processed_hb"] = "vendor_processed_hb"


class DataManifest(BaseModel):
    schema_version: str = "0.2.0"
    data_branch: Literal["vendor_processed_hb"] = "vendor_processed_hb"
    derivatives_contract: str = "1.0.0"
    signal_provenance_uri: str = ""
    population_manifest_uri: str = ""
    events_uri: str = ""
    contrast_matrix_uri: str = ""
    frozen_input_sha256: dict[str, str] = Field(default_factory=dict)
    runs: list[ProcessedHbRun] = Field(default_factory=list)


@dataclass(frozen=True)
class ProcessedHbChannel:
    channel: str
    vendor_channel_number: int
    original_column_name: str
    model_included: bool = True


@dataclass(frozen=True)
class InputProvenance:
    input_uri: str
    local_path: str
    sha256: str
    size_bytes: int
    parser_name: str
    parser_version: str
    encoding: str
    declared_points: int | None
    actual_points: int
    first_timestamp_s: float
    last_timestamp_s: float
    duration_s: float
    native_sfreq_hz: float
    dt_min_s: float
    dt_median_s: float
    dt_max_s: float
    dt_mad_s: float
    dt_iqr_s: float
    jitter_abs_max_s: float
    duplicate_timestamp_count: int
    channel_count: int
    absolute_unit_verified: bool = False
    regularized: bool = False
    target_sfreq_hz: float | None = None
    interpolation_method: str | None = None
    max_time_deviation_s: float | None = None
    hbt_check_status: str = "unavailable"
    hbt_mae: float | None = None
    hbt_rmse: float | None = None
    hbt_max_abs_error: float | None = None
    hbt_error_quantiles: tuple[float, ...] = ()
    hbt_tolerance_exceedance_fraction: float | None = None
    warning_codes: tuple[str, ...] = ()
    parser_status: str = "pass"


@dataclass(frozen=True)
class VendorHeader:
    sections: dict[str, dict[str, str]] = field(default_factory=dict)
    declared_points: int | None = None
    declared_channels: int | None = None
    field_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParserQC:
    status: str
    warnings: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    metrics: dict[str, float | int | str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessedHbRecording:
    native_timestamps_s: np.ndarray
    hbo: np.ndarray
    hbr: np.ndarray
    hbt_validation: np.ndarray | None
    channels: tuple[ProcessedHbChannel, ...]
    task_values: np.ndarray | None
    mark_values: np.ndarray | None
    count_values: np.ndarray | None
    header: VendorHeader
    provenance: InputProvenance
    absolute_unit_verified: Literal[False] = False

    def __post_init__(self) -> None:
        n = self.native_timestamps_s.size
        if self.hbo.ndim != 2 or self.hbr.ndim != 2 or self.hbo.shape != self.hbr.shape:
            raise ValueError("hbo and hbr must be matching channel x sample arrays")
        if self.hbo.shape[1] != n or len(self.channels) != self.hbo.shape[0]:
            raise ValueError("channel/sample dimensions do not match channel map and timestamps")
