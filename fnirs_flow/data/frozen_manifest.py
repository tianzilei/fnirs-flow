"""Manifest-driven discovery for processed-Hb studies."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from fnirs_flow.data.processed_hb_models import DataManifest, ProcessedHbRun


def _rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _resolve(uri_or_path: str, root: str | Path | None) -> Path:
    p = Path(uri_or_path)
    if p.exists():
        return p
    if root and not uri_or_path.startswith("external-data://"):
        candidate = Path(root) / uri_or_path
        if candidate.exists():
            return candidate
    raise FileNotFoundError(uri_or_path)


def discover_frozen_processed_hb(
    signal_provenance_csv: str | Path,
    population_manifest_csv: str | Path,
    *,
    runtime_root: str | Path | None = None,
    events_uri: str = "",
    contrast_matrix_uri: str = "",
) -> DataManifest:
    """Join frozen tables by explicit ``fnirs_record_id`` (never filenames)."""
    signal_rows = _rows(signal_provenance_csv)
    population_rows = _rows(population_manifest_csv)

    def index(rows: list[dict[str, str]], name: str) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        for row in rows:
            key = row.get("fnirs_record_id", "").strip()
            if not key or key in result:
                raise ValueError(f"missing or duplicate fnirs_record_id in {name}: {key!r}")
            result[key] = row
        return result

    signals, populations = index(signal_rows, "signal provenance"), index(population_rows, "population manifest")
    runs: list[ProcessedHbRun] = []
    for record_id, pop in populations.items():
        signal = signals.get(record_id)
        if signal is None:
            runs.append(
                ProcessedHbRun(
                    linked_record_id=pop.get("linked_record_id", ""),
                    fnirs_record_id=record_id,
                    record_pair_id=pop.get("record_pair_id", record_id),
                    subject_id=pop.get("subject_id", ""),
                    session_id=pop.get("session_id", ""),
                    signal_uri=pop.get("fnirs_signal_uri", pop.get("fnirs_signal_path", "")),
                    artifact_mask_uri=pop.get("artifact_mask_uri", ""),
                    artifact_mask_sha256=pop.get("artifact_mask_sha256", ""),
                    runtime_signal_path="",
                    analysis_included=False,
                    frozen_exclusion_reason="SIGNAL_PROVENANCE_MISSING",
                )
            )
            continue
        source = signal.get("fnirs_signal_path", signal.get("fnirs_signal_uri", ""))
        runtime = ""
        sha = signal.get("input_sha256", "")
        try:
            local = _resolve(source, runtime_root)
            runtime = str(local)
            if not sha:
                sha = hashlib.sha256(local.read_bytes()).hexdigest()
        except FileNotFoundError:
            pass
        included = str(pop.get("analysis_included", pop.get("include", "true"))).casefold() in {"1", "true", "yes", "y"}
        runs.append(
            ProcessedHbRun(
                linked_record_id=pop.get("linked_record_id", signal.get("linked_record_id", "")),
                fnirs_record_id=record_id,
                record_pair_id=pop.get("record_pair_id", signal.get("record_pair_id", record_id)),
                subject_id=pop.get("subject_id", signal.get("subject_id", "")),
                session_id=pop.get("session_id", signal.get("session_id", "")),
                signal_uri=source,
                artifact_mask_uri=pop.get("artifact_mask_uri", signal.get("artifact_mask_uri", "")),
                artifact_mask_sha256=pop.get(
                    "artifact_mask_sha256", signal.get("artifact_mask_sha256", "")
                ),
                runtime_signal_path=runtime,
                input_sha256=sha,
                declared_channel_count=(
                    int(signal["channel_count"]) if signal.get("channel_count", "").strip() else None
                ),
                sync_grade=pop.get("sync_grade", ""),
                event_primary_eligible=pop.get("event_primary_eligible", "").casefold() in {"1", "true", "yes"},
                lag_primary_eligible=pop.get("lag_primary_eligible", "").casefold() in {"1", "true", "yes"},
                observed_coverage=pop.get("observed_coverage"),
                analysis_included=included,
                frozen_exclusion_reason=pop.get("frozen_exclusion_reason") or None,
            )
        )

    def digest(path: str | Path) -> str:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    return DataManifest(
        signal_provenance_uri=str(signal_provenance_csv),
        population_manifest_uri=str(population_manifest_csv),
        events_uri=events_uri,
        contrast_matrix_uri=contrast_matrix_uri,
        frozen_input_sha256={
            "signal_provenance": digest(signal_provenance_csv),
            "population_manifest": digest(population_manifest_csv),
            **({"events": digest(events_uri)} if events_uri else {}),
            **({"contrast_matrix": digest(contrast_matrix_uri)} if contrast_matrix_uri else {}),
        },
        runs=runs,
    )
