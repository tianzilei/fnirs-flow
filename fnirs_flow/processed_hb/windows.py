"""Frozen processed-Hb windows, channel/window QC and feature extraction.

The functions in this module are deliberately data-oriented: they accept
``ProcessedHbData`` instances as well as small duck-typed objects/dicts used by
project presets and tests.  No project-specific t7--t11 values are hard-coded.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROCESSED_HB_FEATURE_NAMES = (
    "mean",
    "sd",
    "median",
    "iqr",
    "min",
    "max",
    "linear_slope",
    "auc_abs_signal",
)


def processed_hb_feature_dictionary() -> dict[str, Any]:
    """Return the versioned mathematical contract used by feature extraction."""
    return {
        "contract_version": "processed_hb_channel_window_features_v1",
        "names": list(PROCESSED_HB_FEATURE_NAMES),
        "chromophores": ["hbo", "hbr"],
        "sd": {"definition": "sample_standard_deviation", "ddof": 1, "minimum_samples": 2},
        "iqr": {"definition": "q75_minus_q25", "quantile_method": "linear"},
        "linear_slope": {
            "definition": "ordinary_least_squares",
            "time_axis": "observed_time_s",
            "intercept": True,
            "minimum_samples": 2,
        },
        "auc_abs_signal": {
            "definition": "integral_abs_signal",
            "integration": "trapezoid",
            "time_axis": "observed_time_s",
            "single_sample_value": 0.0,
        },
        "missing_artifact_policy": "exclude_masked_and_nonfinite_without_imputation",
        "invalid_channel_window_policy": "retain_rows_with_nan_and_reason_code",
        "hbt_role": "audit_only",
        "default_ml_chromophores": ["hbo", "hbr"],
    }


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class FrozenWindow:
    window_id: str
    start_s: float
    end_s: float
    closure: str = "left"
    anchor_type: str = ""
    anchor_id: str = ""
    available_by_s: Mapping[str, Any] | None = None
    window_set_version: str = ""
    config_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.window_id:
            raise ValueError("window_id is required")
        if not (math.isfinite(float(self.start_s)) and math.isfinite(float(self.end_s))):
            raise ValueError("window boundaries must be finite")
        if float(self.end_s) <= float(self.start_s):
            raise ValueError("window end_s must be greater than start_s")
        if self.closure != "left":
            raise ValueError("only left-closed [start,end) windows are supported")

    def contains(self, time_s: float) -> bool:
        return self.start_s <= float(time_s) < self.end_s

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "closure": self.closure,
            "anchor_type": self.anchor_type,
            "anchor_id": self.anchor_id,
            "available_by_s": dict(self.available_by_s or {}),
            "window_set_version": self.window_set_version,
            "config_sha256": self.config_sha256,
        }


@dataclass(frozen=True)
class FrozenWindowSet:
    windows: tuple[FrozenWindow, ...]
    window_set_version: str = ""
    config_sha256: str = ""
    config_path: str = ""
    closure: str = "left"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ids = [w.window_id for w in self.windows]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate window_id in window set")
        ordered = sorted(self.windows, key=lambda w: w.start_s)
        for prev, cur in zip(ordered, ordered[1:]):
            if cur.start_s < prev.end_s:
                raise ValueError(f"overlapping windows: {prev.window_id}, {cur.window_id}")
        if self.closure != "left":
            raise ValueError("window-set closure must be left")

    def __iter__(self):
        return iter(self.windows)

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_set_version": self.window_set_version,
            "config_sha256": self.config_sha256,
            "closure": self.closure,
            "windows": [w.as_dict() for w in self.windows],
            **dict(self.metadata),
        }


def ingest_frozen_window_set(config: str | Path | Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> FrozenWindowSet:
    """Load and validate a frozen window set from JSON, mapping or rows."""
    config_path = ""
    if isinstance(config, (str, Path)):
        path = Path(config)
        config_path = str(path.expanduser().resolve())
        raw_bytes = path.read_bytes()
        payload = json.loads(raw_bytes.decode("utf-8"))
        config_sha = _sha256_bytes(raw_bytes)
    else:
        payload = config
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        config_sha = _sha256_bytes(canonical)
    if isinstance(payload, Mapping):
        rows = payload.get("windows", payload.get("items", payload.get("window_set", [])))
        if not rows and {"window_id", "start_s", "end_s"}.issubset(payload):
            rows = [payload]
        version = str(payload.get("window_set_version", payload.get("version", "")))
        closure = str(payload.get("closure", "left"))
        metadata = {
            k: v
            for k, v in payload.items()
            if k not in {"windows", "items", "window_set", "window_set_version", "version", "closure"}
        }
    else:
        rows, version, closure, metadata = payload, "", "left", {}
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
        raise ValueError("window configuration must contain a non-empty windows sequence")
    windows = tuple(
        FrozenWindow(
            window_id=str(row["window_id"]),
            start_s=float(row["start_s"]),
            end_s=float(row["end_s"]),
            closure=str(row.get("closure", closure)),
            anchor_type=str(row.get("anchor_type", "")),
            anchor_id=str(row.get("anchor_id", "")),
            available_by_s=row.get("available_by_s"),
            window_set_version=str(row.get("window_set_version", version)),
            config_sha256=str(row.get("config_sha256", config_sha)),
        )
        for row in rows
    )
    return FrozenWindowSet(windows, version, config_sha, config_path, closure, metadata)


def _get_field(data: Any, name: str) -> Any:
    return data.get(name) if isinstance(data, Mapping) else getattr(data, name)


def _normalized_signal(processed_hb: Any) -> tuple[Any, Any, Any, list[str], dict[str, Any]]:
    """Return time x channel arrays for both parser and regularized recordings."""
    import numpy as np

    try:
        times = np.asarray(_get_field(processed_hb, "time_s"), dtype=float)
    except AttributeError:
        times = np.asarray(_get_field(processed_hb, "timestamps_s"), dtype=float)
    hbo = np.asarray(_get_field(processed_hb, "hbo"), dtype=float)
    hbr = np.asarray(_get_field(processed_hb, "hbr"), dtype=float)
    if hbo.shape != hbr.shape or hbo.ndim != 2:
        raise ValueError("processed-Hb arrays must be matching two-dimensional arrays")
    # ProcessedHbData stores samples x channels; RegularizedHbRecording stores
    # channels x samples. Infer orientation from timestamp length.  A few
    # vendor exports retain a longer timestamp vector than the signal matrix;
    # when channel metadata disambiguates the orientation, trim the trailing
    # timestamps rather than rejecting an otherwise usable recording.
    source = getattr(processed_hb, "source", None)
    declared_channels = list(getattr(source, "channels", ())) if source is not None else []
    declared_channel_count = len(declared_channels)
    if hbo.shape[0] == times.size and hbo.shape[1] != times.size:
        pass
    elif hbo.shape[1] == times.size and hbo.shape[0] != times.size:
        hbo, hbr = hbo.T, hbr.T
    elif declared_channel_count and hbo.shape[0] == declared_channel_count and hbo.shape[1] <= times.size:
        hbo, hbr = hbo.T, hbr.T
        times = times[: hbo.shape[0]]
    elif declared_channel_count and hbo.shape[1] == declared_channel_count and hbo.shape[0] <= times.size:
        times = times[: hbo.shape[0]]
    elif hbo.shape[0] == times.size == hbo.shape[1]:
        raise ValueError("ambiguous processed-Hb array orientation")
    else:
        raise ValueError("processed-Hb arrays do not match timestamp length")
    try:
        names = list(_get_field(processed_hb, "channel_names"))
    except AttributeError:
        names = list(getattr(source, "channels", ()))
        names = [getattr(c, "channel", str(c)) for c in names]
    if len(names) != hbo.shape[1]:
        names = [f"ch-{i + 1}" for i in range(hbo.shape[1])]
    provenance = getattr(processed_hb, "provenance", None)
    if provenance is None and hasattr(processed_hb, "source"):
        provenance = getattr(processed_hb.source, "provenance", {})
    return times, hbo, hbr, [str(name) for name in names], dict(provenance) if isinstance(provenance, Mapping) else {}


def _longest_true_run(mask: Sequence[bool], times: Sequence[float]) -> float:
    longest = 0.0
    start = None
    for i, bad in enumerate(mask):
        if bad and start is None:
            start = i
        if (not bad or i == len(mask) - 1) and start is not None:
            end = i if not bad else i + 1
            if end - 1 >= start:
                dt = float(times[1] - times[0]) if len(times) > 1 else 0.0
                longest = max(longest, float(times[end - 1] - times[start] + dt))
            start = None
    return longest


def evaluate_processed_hb_window_qc(
    processed_hb: Any,
    windows: FrozenWindowSet | Iterable[FrozenWindow] | Mapping[str, Any],
    channel_annotations: Any = None,
    artifact_mask: Any = None,
    *,
    min_valid_sample_fraction: float = 0.80,
    max_artifact_duration_s: float = 10.0,
    qc_policy_id: str = "processed_hb_window_qc_v1",
    qc_policy_version: str = "1",
    input_sha256: str = "",
    artifact_mask_sha256: str = "",
) -> list[dict[str, Any]]:
    """Return one QC record per channel/window, evaluating HbO and HbR jointly."""
    import numpy as np

    if not isinstance(windows, FrozenWindowSet):
        windows = ingest_frozen_window_set(windows) if isinstance(windows, Mapping) else FrozenWindowSet(tuple(windows))
    times, hbo, hbr, names, provenance = _normalized_signal(processed_hb)
    n, channels = len(times), hbo.shape[1]
    mask = np.zeros((n, channels), dtype=bool)
    if artifact_mask is not None:
        arr = np.asarray(artifact_mask, dtype=bool)
        if arr.ndim == 1:
            if arr.shape[0] != n:
                raise ValueError("artifact mask length must match time samples")
            mask = np.broadcast_to(arr[:, None], (n, channels)).copy()
        elif arr.ndim == 2:
            mask = np.broadcast_to(arr, (n, channels)).copy()
        else:
            raise ValueError("artifact mask must be one- or two-dimensional")
    annotation_ids = set()
    annotation_by_id: dict[str, Mapping[str, Any]] = {}
    if channel_annotations is not None:
        rows = channel_annotations.values() if isinstance(channel_annotations, Mapping) else channel_annotations
        for row in rows:
            key = str(row.get("channel_id", row.get("vendor_channel_number", "")))
            annotation_ids.add(key)
            annotation_by_id[key] = row
    results: list[dict[str, Any]] = []
    dt = float(np.median(np.diff(times))) if n > 1 else 0.0
    for window in windows:
        sel = (times >= window.start_s) & (times < window.end_s)
        expected = int(round((window.end_s - window.start_s) / dt)) if dt > 0 else int(sel.sum())
        for idx, channel_id in enumerate(names):
            finite = np.isfinite(hbo[:, idx]) & np.isfinite(hbr[:, idx])
            in_window = sel
            valid = finite & ~mask[:, idx] & in_window
            actual = int(in_window.sum())
            valid_n = int(valid.sum())
            artifact_n = int((mask[:, idx] & in_window).sum())
            frac = valid_n / expected if expected else 0.0
            longest = _longest_true_run(mask[:, idx] & in_window, times)
            reason = ""
            status = "pass"
            if (channel_annotations is not None) and str(channel_id) not in annotation_ids:
                status, reason = "fail", "CHANNEL_MAPPING_MISSING"
            elif actual == 0:
                status, reason = "fail", "TIME_WINDOW_OUT_OF_COVERAGE"
            elif frac < min_valid_sample_fraction:
                status = "fail"
                reason = "NONFINITE_SIGNAL" if valid_n < actual - artifact_n else "INSUFFICIENT_SAMPLE_FRACTION"
            elif longest > max_artifact_duration_s:
                status, reason = "fail", "ARTIFACT_SEGMENT_TOO_LONG"
            results.append(
                {
                    "window_id": window.window_id,
                    "channel_id": str(channel_id),
                    **{
                        key: annotation_by_id.get(str(channel_id), {}).get(key, "")
                        for key in (
                            "vendor_channel_number",
                            "source_id",
                            "detector_id",
                            "source_detector_pair",
                            "roi_label",
                            "aal_label",
                            "laterality",
                            "probe_role",
                        )
                    },
                    "expected_sample_count": expected,
                    "actual_sample_count": actual,
                    "valid_sample_count": valid_n,
                    "valid_sample_fraction": frac,
                    "artifact_sample_count": artifact_n,
                    "longest_artifact_duration_s": longest,
                    "qc_status": status,
                    "qc_reason_code": reason,
                    "qc_policy_id": qc_policy_id,
                    "qc_policy_version": qc_policy_version,
                    "input_sha256": input_sha256 or str(provenance.get("sha256", "")),
                    "artifact_mask_sha256": artifact_mask_sha256,
                    "finite_sample_count": int(
                        (np.isfinite(hbo[in_window, idx]) & np.isfinite(hbr[in_window, idx])).sum()
                    ),
                }
            )
    return results


def aggregate_window_modality_availability(
    qc_rows: Iterable[Mapping[str, Any]], *, min_valid_channel_fraction: float = 0.50
) -> list[dict[str, Any]]:
    """Aggregate channel QC without merging identically named windows across records."""
    identity_fields = ("subject_id", "session_id", "record_pair_id", "window_id")
    grouped: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for row in qc_rows:
        key = (
            str(row.get("subject_id", "")),
            str(row.get("session_id", "")),
            str(row.get("record_pair_id", "")),
            str(row.get("window_id", "")),
        )
        grouped.setdefault(key, []).append(row)
    out = []
    for identity, rows in grouped.items():
        expected = len(rows)
        valid = sum(str(r.get("qc_status", "")) == "pass" for r in rows)
        frac = valid / expected if expected else 0.0
        out.append(
            {
                **dict(zip(identity_fields, identity, strict=True)),
                "expected_channel_count": expected,
                "valid_channel_count": valid,
                "valid_channel_fraction": frac,
                "fnirs_available": frac >= min_valid_channel_fraction,
                "min_valid_channel_fraction": min_valid_channel_fraction,
            }
        )
    return out


def extract_processed_hb_channel_window_features(
    processed_hb: Any,
    qc_rows: Iterable[Mapping[str, Any]],
    windows: FrozenWindowSet | Iterable[FrozenWindow],
    channel_annotations: Any = None,
    artifact_mask: Any = None,
    *,
    feature_names: Sequence[str] | None = None,
    sd_ddof: int = 1,
    input_sha256: str = "",
    artifact_mask_sha256: str = "",
) -> list[dict[str, Any]]:
    import numpy as np

    if not isinstance(windows, FrozenWindowSet):
        windows = FrozenWindowSet(tuple(windows))
    times, hbo, hbr, names, provenance = _normalized_signal(processed_hb)
    qc_map = {(str(r["window_id"]), str(r["channel_id"])): r for r in qc_rows}
    if sd_ddof not in (0, 1):
        raise ValueError("sd_ddof must be 0 or 1")
    mask = np.zeros((len(times), len(names)), dtype=bool)
    if artifact_mask is not None:
        arr = np.asarray(artifact_mask, dtype=bool)
        if arr.ndim == 1:
            mask = np.broadcast_to(arr[:, None], mask.shape).copy()
        elif arr.ndim == 2:
            mask = (
                arr
                if arr.shape == mask.shape
                else arr.T
                if arr.T.shape == mask.shape
                else (_ for _ in ()).throw(ValueError("artifact mask shape mismatch"))
            )
        else:
            raise ValueError("artifact mask must be one- or two-dimensional")
    feats = list(feature_names or PROCESSED_HB_FEATURE_NAMES)
    unknown = sorted(set(feats) - set(PROCESSED_HB_FEATURE_NAMES))
    if unknown:
        raise ValueError(f"unsupported processed-Hb feature names: {unknown}")
    rows: list[dict[str, Any]] = []
    # Annotation metadata are carried through to the long feature table when
    # available; this keeps channel-level identity intact before any ROI-level
    # aggregation is performed by downstream consumers.
    annotation_by_id: dict[str, Mapping[str, Any]] = {}
    annotations = (
        channel_annotations if channel_annotations is not None else getattr(processed_hb, "channel_annotations", None)
    )
    if annotations is not None:
        source = annotations.values() if isinstance(annotations, Mapping) else annotations
        annotation_by_id = {str(a.get("channel_id", a.get("vendor_channel_number", ""))): a for a in source}
    for window in windows:
        sel = (times >= window.start_s) & (times < window.end_s)
        for idx, channel_id in enumerate(names):
            qc = qc_map.get((window.window_id, str(channel_id)), {})
            status, reason = qc.get("qc_status", "fail"), qc.get("qc_reason_code", "MISSING_QC")
            for chrom, signal in (("hbo", hbo[:, idx]), ("hbr", hbr[:, idx])):
                valid_sel = sel & ~mask[:, idx] & np.isfinite(signal)
                x = signal[valid_sel]
                t = times[valid_sel]
                ok = status == "pass" and len(x) > 0
                values: dict[str, float] = {f: float("nan") for f in feats}
                if ok:
                    for f in feats:
                        if f == "mean":
                            values[f] = float(np.mean(x))
                        elif f == "sd":
                            values[f] = float(np.std(x, ddof=sd_ddof)) if len(x) > sd_ddof else float("nan")
                        elif f == "median":
                            values[f] = float(np.median(x))
                        elif f == "iqr":
                            values[f] = float(
                                np.quantile(x, 0.75, method="linear") - np.quantile(x, 0.25, method="linear")
                            )
                        elif f == "min":
                            values[f] = float(np.min(x))
                        elif f == "max":
                            values[f] = float(np.max(x))
                        elif f == "linear_slope":
                            values[f] = float(np.polyfit(t, x, 1)[0]) if len(x) > 1 and np.ptp(t) > 0 else float("nan")
                        elif f == "auc_abs_signal":
                            values[f] = (
                                float(
                                    np.sum(
                                        np.diff(t)
                                        * (np.abs(x[:-1]) + np.abs(x[1:]))
                                        * 0.5
                                    )
                                )
                                if len(x) > 1
                                else 0.0
                            )
                for feature_name, value in values.items():
                    ann = annotation_by_id.get(str(channel_id), {})
                    rows.append(
                        {
                            "window_id": window.window_id,
                            "window_start_s": window.start_s,
                            "window_end_s": window.end_s,
                            "channel_id": str(channel_id),
                            "vendor_channel_number": ann.get("vendor_channel_number", ""),
                            "source_id": ann.get("source_id", ""),
                            "detector_id": ann.get("detector_id", ""),
                            "source_detector_pair": ann.get("source_detector_pair", ""),
                            "roi_label": ann.get("roi_label", ""),
                            "aal_label": ann.get("aal_label", ""),
                            "laterality": ann.get("laterality", ""),
                            "chromophore": chrom,
                            "feature_name": feature_name,
                            "feature_value": value,
                            "qc_status": status if ok else "fail",
                            "qc_reason_code": "" if ok else reason,
                            "input_sha256": input_sha256 or str(provenance.get("sha256", "")),
                            "artifact_mask_sha256": artifact_mask_sha256,
                            "mapping_sha256": ann.get("mapping_sha256", ""),
                            "software_version": "",
                        }
                    )
    return rows
