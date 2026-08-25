"""Strict, auditable ingestion of frozen event tables."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FrozenEvent:
    fnirs_record_id: str
    onset: float
    duration: float
    trial_type: str
    window_id: str
    event_number: str = ""
    event_time_layer: str = ""
    event_source: str = "frozen_manifest"
    sync_uncertainty_s: float | None = None
    event_eligible: bool = True
    duplicate_of_window: str = ""
    source_row: int = 0


@dataclass(frozen=True)
class FrozenEventSet:
    record_id: str
    events: tuple[FrozenEvent, ...]
    audit: tuple[dict[str, str], ...]


def ingest_frozen_events(
    path: str | Path,
    record_id: str,
    *,
    coverage: tuple[float, float] | None = None,
    coverage_tolerance_s: float = 0.0,
) -> FrozenEventSet:
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    required = {"fnirs_record_id", "onset", "duration", "trial_type", "window_id"}
    if rows and not required.issubset(rows[0]):
        raise ValueError(f"events table missing columns: {sorted(required - set(rows[0]))}")
    seen: set[str] = set()
    events: list[FrozenEvent] = []
    audit: list[dict[str, str]] = []
    for source_row, row in enumerate(rows, 2):
        if row.get("fnirs_record_id", "") != record_id:
            continue
        wid = row.get("window_id", "").strip()
        try:
            onset, duration = float(row["onset"]), float(row["duration"])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"invalid event timing for {wid}") from exc
        uncertainty = float(row["sync_uncertainty_s"]) if row.get("sync_uncertainty_s") else None
        if not math.isfinite(onset) or not math.isfinite(duration) or (
            uncertainty is not None and not math.isfinite(uncertainty)
        ):
            raise ValueError(f"non-finite event timing for {wid}")
        eligible = row.get("event_eligible", "true").casefold() in {"1", "true", "yes", "y"}
        duplicate_ref = row.get("duplicate_of_window", "").strip()
        reason = ""
        if not wid or wid in seen:
            eligible, reason = False, "DUPLICATE_WINDOW_ID"
        elif onset < 0 or duration < 0 or (
            coverage
            and (
                onset < coverage[0] - coverage_tolerance_s
                or onset + duration > coverage[1] + coverage_tolerance_s
            )
        ):
            eligible, reason = False, "EVENT_OUTSIDE_COVERAGE"
        elif duplicate_ref:
            if duplicate_ref == wid or duplicate_ref not in seen:
                eligible, reason = False, "INVALID_DUPLICATE_REFERENCE"
            else:
                eligible, reason = False, "DUPLICATE_EVENT_AUDIT_ONLY"
        seen.add(wid)
        event = FrozenEvent(
            record_id,
            onset,
            duration,
            row.get("trial_type", ""),
            wid,
            row.get("event_number", ""),
            row.get("event_time_layer", ""),
            row.get("event_source", "frozen_manifest"),
            uncertainty,
            eligible,
            duplicate_ref,
            source_row,
        )
        events.append(event)
        audit.append(
            {
                "source_row": str(source_row),
                "window_id": wid,
                "status": "eligible" if eligible else "excluded",
                "reason_code": reason,
            }
        )
    return FrozenEventSet(record_id, tuple(events), tuple(audit))
