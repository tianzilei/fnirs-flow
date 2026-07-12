"""Dataset discovery: discover public datasets and generate data manifests."""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from fnirs_flow.data.manifest import (
    DataFile,
    DataManifest,
    DataSource,
    SubjectSessionRun,
    write_data_manifest,
)
from fnirs_flow.data.registry import DatasetEntry, DatasetRegistry


def _compute_file_hash(filepath: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _discover_mne_dataset(entry: DatasetEntry, outdir: Path) -> DataManifest:
    """Discover files for an MNE-NIRS dataset."""
    try:
        from mne.datasets import fnirs_motor

        local_root = Path(fnirs_motor.data_path())
    except (ImportError, OSError, RuntimeError):
        local_root = Path.home() / "mne_data" / entry.folder_name

    files: list[DataFile] = []
    subject_runs: list[SubjectSessionRun] = []

    if local_root.exists():
        # Find SNIRF files
        snirf_files = list(local_root.rglob("*.snirf"))
        for f in snirf_files:
            rel_path = str(f.relative_to(local_root))
            files.append(
                DataFile(
                    path=rel_path,
                    sha256=_compute_file_hash(f),
                    size_bytes=f.stat().st_size,
                    role="raw_snirf",
                )
            )

        # Parse subject/session/run from filenames
        # Typical pattern: sub-XX_task-XX_run-XX.snirf
        for f in snirf_files:
            name = f.stem
            parts = {}
            for part in name.split("_"):
                if part.startswith("sub-"):
                    parts["subject"] = part[4:]
                elif part.startswith("ses-"):
                    parts["session"] = part[4:]
                elif part.startswith("run-"):
                    parts["run"] = part[4:]
            subject_runs.append(
                SubjectSessionRun(
                    subject=parts.get("subject", ""),
                    session=parts.get("session", ""),
                    run=parts.get("run", ""),
                    path=str(f),
                )
            )

    return DataManifest(
        dataset_id=entry.dataset_id,
        source=DataSource(
            kind=entry.source_kind,
            url=entry.url,
            doi=entry.doi,
            citation=entry.citation,
        ),
        local_root=str(local_root),
        files=files,
        subject_session_runs=subject_runs,
        access_instructions=f"Data available at {entry.url}" if entry.url else "",
        license=entry.license,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _find_workspace_root() -> Path:
    """Find the repository root from this module location."""
    return Path(__file__).resolve().parents[2]


def _parse_bids_entities(path: Path) -> dict[str, str]:
    """Parse common BIDS filename entities from a file path."""
    entities: dict[str, str] = {}
    for part in path.stem.split("_"):
        if "-" not in part:
            continue
        key, value = part.split("-", 1)
        if key in {"sub", "ses", "task", "run"}:
            entities[key] = value
    if "sub" not in entities:
        for parent in path.parents:
            if parent.name.startswith("sub-"):
                entities["sub"] = parent.name[4:]
                break
    return entities


def _is_ignored_sidecar(path: Path) -> bool:
    """Ignore filesystem metadata files such as macOS AppleDouble sidecars."""
    return any(part.startswith("._") for part in path.parts)


def _discover_local_bids_nirs(entry: DatasetEntry, outdir: Path) -> DataManifest:
    """Discover local BIDS-NIRS files and generate a manifest."""
    local_root = (_find_workspace_root() / entry.folder_name).resolve()

    files: list[DataFile] = []
    subject_runs: list[SubjectSessionRun] = []

    if local_root.exists():
        for f in sorted(p for p in local_root.rglob("*") if p.is_file() and not _is_ignored_sidecar(p)):
            rel_path = str(f.relative_to(local_root))
            role = "metadata"
            if f.suffix.lower() == ".snirf":
                role = "raw_snirf"
            elif f.name.endswith("_events.tsv"):
                role = "events"
            elif f.name.endswith("_channels.tsv"):
                role = "channels"
            elif f.name.endswith("_nirs.json"):
                role = "nirs_sidecar"

            files.append(
                DataFile(
                    path=rel_path,
                    sha256=_compute_file_hash(f),
                    size_bytes=f.stat().st_size,
                    role=role,
                )
            )

        for f in sorted(p for p in local_root.rglob("*_nirs.snirf") if not _is_ignored_sidecar(p)):
            rel_path = str(f.relative_to(local_root))
            entities = _parse_bids_entities(f)
            # Find matching events TSV for this run
            events_path = ""
            events_suffix = "_events.tsv"
            for ef in local_root.rglob(f"*{events_suffix}"):
                ef_entities = _parse_bids_entities(ef)
                if (
                    ef_entities.get("sub") == entities.get("sub")
                    and ef_entities.get("ses") == entities.get("ses")
                    and ef_entities.get("task") == entities.get("task")
                    and ef_entities.get("run") == entities.get("run")
                ):
                    events_path = str(ef)
                    break
            subject_runs.append(
                SubjectSessionRun(
                    subject=entities.get("sub", ""),
                    session=entities.get("ses", ""),
                    run=entities.get("run", ""),
                    task=entities.get("task", ""),
                    path=str(f),
                    relative_path=rel_path,
                    data_sha256=_compute_file_hash(f),
                    source_file_role="raw_snirf",
                    events_path=events_path,
                )
            )

    return DataManifest(
        dataset_id=entry.dataset_id,
        source=DataSource(
            kind=entry.source_kind,
            url=entry.url,
            doi=entry.doi,
            citation=entry.citation,
        ),
        local_root=str(local_root),
        files=files,
        subject_session_runs=subject_runs,
        access_instructions=f"Local BIDS-NIRS dataset expected at {local_root}",
        license=entry.license,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def discover_dataset(dataset_id: str, outdir: str | Path) -> DataManifest:
    """Discover a dataset and generate data_manifest.json.

    Writes data_manifest.json and run_table.csv to ``outdir/compiled/``
    following the derivatives-style layout convention.
    """
    outdir = Path(outdir)
    compiled_dir = outdir / "compiled"
    compiled_dir.mkdir(parents=True, exist_ok=True)

    registry = DatasetRegistry()
    entry = registry.get(dataset_id)
    if entry is None:
        raise ValueError(f"Unknown dataset: {dataset_id}. Available: {registry.list_ids()}")

    if entry.source_kind == "mne_nirs_dataset":
        manifest = _discover_mne_dataset(entry, compiled_dir)
    elif entry.source_kind == "local_bids_nirs":
        manifest = _discover_local_bids_nirs(entry, compiled_dir)
    else:
        manifest = DataManifest(
            dataset_id=dataset_id,
            source=DataSource(kind=entry.source_kind, url=entry.url),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    write_data_manifest(manifest, compiled_dir)

    # Write run_table.csv to compiled/
    run_table_path = compiled_dir / "run_table.csv"
    with open(run_table_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "subject",
                "session",
                "run",
                "task",
                "path",
                "relative_path",
                "data_sha256",
            ]
        )
        for sr in manifest.subject_session_runs:
            writer.writerow(
                [
                    sr.subject,
                    sr.session,
                    sr.run,
                    sr.task,
                    sr.path,
                    sr.relative_path,
                    sr.data_sha256,
                ]
            )

    return manifest
