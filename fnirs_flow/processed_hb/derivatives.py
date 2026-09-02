"""Derivative bundle writer and reproducibility freeze manifest."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import platform
import sys
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, rows: Iterable[Mapping[str, Any]], fields: list[str] | None = None) -> Path:
    rows = list(rows)
    fields = list(fields or [])
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", newline="", encoding="utf-8") as f:
        if fields:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(
                    {
                        k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list, tuple)) else v)
                        for k, v in r.items()
                    }
                )
    return path


def write_processed_hb_ml_derivatives(
    outdir: str | Path,
    *,
    features=(),
    qc=(),
    availability=(),
    annotations=(),
    input_manifest=(),
    feature_dictionary: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    root = Path(outdir)
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "features": _write(
            root / "channel_window_features.csv.gz",
            features,
            [
                "subject_id",
                "session_id",
                "record_pair_id",
                "window_id",
                "window_start_s",
                "window_end_s",
                "channel_id",
                "vendor_channel_number",
                "source_id",
                "detector_id",
                "source_detector_pair",
                "roi_label",
                "aal_label",
                "laterality",
                "chromophore",
                "feature_name",
                "feature_value",
                "qc_status",
                "qc_reason_code",
                "input_sha256",
                "artifact_mask_sha256",
                "mapping_sha256",
                "software_version",
            ],
        ),
        "qc": _write(
            root / "channel_window_qc.csv.gz",
            qc,
            [
                "subject_id",
                "session_id",
                "record_pair_id",
                "window_id",
                "channel_id",
                "expected_sample_count",
                "actual_sample_count",
                "finite_sample_count",
                "valid_sample_count",
                "valid_sample_fraction",
                "artifact_sample_count",
                "longest_artifact_duration_s",
                "qc_status",
                "qc_reason_code",
                "qc_policy_id",
                "qc_policy_version",
                "input_sha256",
                "artifact_mask_sha256",
            ],
        ),
        "availability": _write(root / "window_modality_availability.csv", availability),
        "annotations": _write(root / "channel_annotation_table.csv", annotations),
        "input_manifest": _write(root / "input_manifest.csv", input_manifest),
    }
    fd = root / "feature_dictionary.json"
    fd.write_text(json.dumps(feature_dictionary or {}, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["feature_dictionary"] = fd
    pv = root / "processing_provenance.json"
    pv.write_text(json.dumps(dict(provenance or {}), indent=2, ensure_ascii=False), encoding="utf-8")
    paths["provenance"] = pv
    return paths


def freeze_processed_hb_feature_artifacts(
    outdir: str | Path,
    *,
    config_path: str | Path | None = None,
    input_manifest_path: str | Path | None = None,
    mapping_path: str | Path | None = None,
    software_version: str = "",
    git_commit: str = "",
    command: str = "",
    approval_status: str = "pending",
    random_seed: int | None = None,
    freeze_id: str | None = None,
    overwrite: bool = False,
) -> Path:
    root = Path(outdir)
    files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and not (p.name.startswith("feature_freeze_manifest") and p.suffix == ".json")
    )
    hashes = {p.relative_to(root).as_posix(): _sha(p) for p in files}

    def digest(path):
        return _sha(Path(path)) if path and Path(path).exists() else ""

    dependency_versions = {}
    for package in ("fnirs-flow", "numpy", "scipy", "scikit-learn", "pydantic"):
        try:
            dependency_versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            dependency_versions[package] = "not-installed"

    def portable_name(path: str | Path | None) -> str:
        return Path(path).name if path else ""

    manifest = {
        "freeze_version": "1.0.0",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "software_version": software_version,
        "git_commit": git_commit,
        "python": sys.version,
        "platform": platform.platform(),
        "dependency_versions": dependency_versions,
        "config_path": portable_name(config_path),
        "config_sha256": digest(config_path),
        "input_manifest_path": portable_name(input_manifest_path),
        "input_manifest_sha256": digest(input_manifest_path),
        "mapping_path": portable_name(mapping_path),
        "mapping_sha256": digest(mapping_path),
        "feature_table_sha256": hashes.get("channel_window_features.csv.gz", ""),
        "qc_table_sha256": hashes.get("channel_window_qc.csv.gz", ""),
        "artifact_sha256": hashes,
        "command": command,
        "random_seed": random_seed,
        "approval_status": approval_status,
    }
    if not software_version or not git_commit:
        raise ValueError("software_version and git_commit are required for a freeze")
    missing_hashes = [
        key
        for key in ("config_sha256", "input_manifest_sha256", "mapping_sha256")
        if not manifest[key]
    ]
    if missing_hashes:
        raise ValueError(f"freeze inputs are required and must exist: {', '.join(missing_hashes)}")
    identity_fields = (
        "software_version",
        "git_commit",
        "config_sha256",
        "input_manifest_sha256",
        "mapping_sha256",
        "feature_table_sha256",
        "qc_table_sha256",
        "artifact_sha256",
        "command",
        "random_seed",
        "approval_status",
    )
    identity_payload = {key: manifest[key] for key in identity_fields}
    identity_sha256 = hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    manifest["freeze_identity_sha256"] = identity_sha256
    target = root / (f"feature_freeze_manifest_{freeze_id}.json" if freeze_id else "feature_freeze_manifest.json")
    if target.exists() and not overwrite:
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
            if existing.get("freeze_identity_sha256") == identity_sha256:
                return target
        except Exception:
            pass
        suffix = f"_{identity_sha256[:12]}"
        stem = target.stem
        target = target.with_name(f"{stem}{suffix}.json")
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if existing.get("freeze_identity_sha256") == identity_sha256:
                return target
            raise FileExistsError(f"freeze identity collision: {target}")
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return target
