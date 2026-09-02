"""Frozen-manifest and event contracts for processed-Hb analysis."""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def read_table(path: str | Path, *, delimiter: str = ",") -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=delimiter)
        if reader.fieldnames is None:
            raise ValueError(f"table has no header: {path}")
        duplicate_fields = sorted({name for name in reader.fieldnames if reader.fieldnames.count(name) > 1})
        if duplicate_fields:
            raise ValueError(f"table has duplicate columns {duplicate_fields}: {path}")
        return [dict(row) for row in reader]


@dataclass(frozen=True)
class FrozenRecord:
    paired_record_id: str
    fnirs_record_id: str
    record_pair_id: str
    signal_path: str
    signal_sha256: str
    sync_grade: str
    event_primary_eligible: bool
    lag_primary_eligible: bool
    fnirs_qc_gate: bool
    paired_signal_gate: bool
    source: dict[str, str]
    provenance: dict[str, str]


def load_frozen_records(
    provenance_csv: str | Path,
    population_csv: str | Path,
) -> list[FrozenRecord]:
    provenance_rows = read_table(provenance_csv)
    population_rows = read_table(population_csv)
    if not population_rows:
        raise ValueError("frozen population manifest has no rows")
    provenance_by_id: dict[str, dict[str, str]] = {}
    for row in provenance_rows:
        fnirs_id = row.get("fnirs_record_id", "").strip()
        # The frozen left join intentionally retains records without an fNIRS
        # signal.  They remain auditable in the source table but are not
        # candidates for processed-Hb execution.
        if not fnirs_id:
            continue
        if fnirs_id in provenance_by_id:
            raise ValueError(f"duplicate non-blank fnirs_record_id in provenance: {fnirs_id}")
        provenance_by_id[fnirs_id] = row

    seen_fnirs: set[str] = set()
    seen_pairs: set[str] = set()
    records: list[FrozenRecord] = []
    for row in population_rows:
        fnirs_id = row.get("fnirs_record_id", "").strip()
        paired_id = row.get("paired_record_id", "").strip()
        if not fnirs_id or not paired_id:
            continue
        pair_id = f"{paired_id}::{fnirs_id}"
        if fnirs_id in seen_fnirs or pair_id in seen_pairs:
            raise ValueError(f"frozen population is not one-to-one at {pair_id}")
        seen_fnirs.add(fnirs_id)
        seen_pairs.add(pair_id)
        provenance = provenance_by_id.get(fnirs_id)
        if provenance is None:
            # A reviewed record match does not imply that the processed-Hb
            # signal exists locally.  Such rows remain in the frozen
            # population audit and are not execution candidates.
            continue
        signal_path = row.get("fnirs_signal_path", "").strip() or provenance.get("fnirs_signal_path", "").strip()
        signal_sha = row.get("fnirs_signal_sha256", "").strip() or provenance.get("sha256", "").strip()
        if not signal_path:
            raise ValueError(f"{fnirs_id}: processed-Hb signal path is blank")
        if not signal_sha:
            raise ValueError(f"{fnirs_id}: processed-Hb SHA-256 is required")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", signal_sha):
            raise ValueError(f"{fnirs_id}: processed-Hb SHA-256 must contain 64 hexadecimal characters")
        if provenance.get("export_stage") not in {"", "vendor_processed_hb_composite"}:
            raise ValueError(f"{fnirs_id}: unsupported export_stage {provenance.get('export_stage')!r}")
        records.append(
            FrozenRecord(
                paired_record_id=paired_id,
                fnirs_record_id=fnirs_id,
                record_pair_id=pair_id,
                signal_path=signal_path,
                signal_sha256=signal_sha,
                sync_grade=row.get("effective_sync_grade", ""),
                event_primary_eligible=parse_bool(row.get("event_primary_eligible")),
                lag_primary_eligible=parse_bool(row.get("lag_primary_eligible")),
                fnirs_qc_gate=parse_bool(row.get("fnirs_qc_gate")),
                paired_signal_gate=parse_bool(row.get("paired_signal_gate")),
                source=row,
                provenance=provenance,
            )
        )
    return records


def load_frozen_events(events_tsv: str | Path) -> dict[str, list[dict[str, str]]]:
    rows = read_table(events_tsv, delimiter="\t")
    grouped: dict[str, list[dict[str, str]]] = {}
    seen_windows: set[tuple[str, str]] = set()
    for row in rows:
        fnirs_id = row.get("fnirs_record_id", "").strip()
        window_id = row.get("window_id", "").strip()
        if not fnirs_id or not window_id:
            raise ValueError("frozen event row has blank fnirs_record_id or window_id")
        key = (fnirs_id, window_id)
        if key in seen_windows:
            raise ValueError(f"duplicate frozen window_id for {fnirs_id}: {window_id}")
        seen_windows.add(key)
        grouped.setdefault(fnirs_id, []).append(row)
    return grouped


def load_frozen_contrasts(contrast_csv: str | Path | None) -> list[dict[str, str]]:
    """Load the frozen contrast table without changing its family decisions."""
    if contrast_csv is None:
        return []
    return read_table(contrast_csv)


def parse_window_weights(value: str) -> tuple[str, dict[str, float]]:
    """Parse estimable ``name:weight`` contrasts or retain global equations."""
    text = value.strip()
    if not text:
        return "empty", {}
    if "=" in text:
        return "global_equation", {}
    weights: dict[str, float] = {}
    for item in text.split(";"):
        name, separator, weight = item.partition(":")
        if not separator or not name.strip():
            raise ValueError(f"invalid window_weights item: {item!r}")
        key = name.strip()
        if key in weights:
            raise ValueError(f"duplicate contrast weight for {key}")
        parsed_weight = float(weight)
        if not math.isfinite(parsed_weight):
            raise ValueError(f"contrast weight for {key} is non-finite")
        weights[key] = parsed_weight
    if not any(value != 0.0 for value in weights.values()):
        raise ValueError("linear contrast must contain at least one non-zero weight")
    return "linear", weights


def audit_events(
    rows: list[dict[str, str]],
    *,
    first_time_s: float,
    last_time_s: float,
    tolerance_s: float = 1e-6,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    audit: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    for row in rows:
        onset = float(row["onset"])
        duration = float(row["duration"])
        if not math.isfinite(onset) or not math.isfinite(duration):
            raise ValueError(f"event {row.get('window_id', '')!r} has non-finite onset or duration")
        eligible = parse_bool(row.get("event_eligible"))
        duplicate_of = row.get("duplicate_of_window", "").strip()
        reasons: list[str] = []
        if onset < first_time_s - tolerance_s:
            reasons.append("onset_before_signal")
        if duration < 0:
            reasons.append("negative_duration")
        if onset + duration > last_time_s + tolerance_s:
            reasons.append("event_exceeds_signal")
        if not eligible:
            reasons.append("event_not_eligible")
        if duplicate_of:
            reasons.append("duplicate_window")
        decision = "accepted" if not reasons else "excluded"
        item: dict[str, Any] = {
            **row,
            "onset": onset,
            "duration": duration,
            "event_eligible": eligible,
            "ingestion_decision": decision,
            "ingestion_reasons": ";".join(reasons),
        }
        audit.append(item)
        if decision == "accepted":
            accepted.append(item)
    accepted.sort(key=lambda row: (float(row["onset"]), str(row["trial_type"])))
    return audit, accepted
