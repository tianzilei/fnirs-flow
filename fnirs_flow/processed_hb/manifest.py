"""Discovery, identity gating and channel annotation contracts for processed-Hb."""

from __future__ import annotations

import csv
import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ChannelAnnotationTable:
    rows: tuple[dict[str, Any], ...]
    mapping_version: str = ""
    mapping_sha256: str = ""

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(path: Path) -> tuple[str, str]:
    text = path.stem
    subject = re.search(r"(?:sub(?:ject)?[-_])([A-Za-z0-9]+)", text, re.I)
    session = re.search(r"(?:ses(?:sion)?[-_])([A-Za-z0-9]+)", text, re.I)
    return (subject.group(1) if subject else text.split("_")[0], session.group(1) if session else "01")


def build_processed_hb_manifest(
    root: str | Path,
    *,
    companion_pattern: str = "{stem}.csv",
    mapping: Mapping[str, str] | None = None,
    expected_channel_count: int | None = None,
    allowed_probe_roles: Iterable[str] = ("subject_re",),
    config_version: str = "1",
    fail_on_error: bool = True,
    output_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Recursively discover ``*_RE.TXT`` and pair companion CSV files.

    Ambiguous/missing pairs and disallowed probe roles are emitted as excluded
    records, preserving an auditable fail-closed decision.
    """
    base = Path(root).expanduser().resolve()
    out = []
    seen_ids = set()
    allowed = set(allowed_probe_roles)
    signals = sorted(set(base.rglob("*_RE.TXT")) | set(base.rglob("*_OP.TXT")))
    for signal in signals:
        rel = signal.relative_to(base).as_posix()
        subject, session = _identity(signal)
        sid = mapping.get(rel, mapping.get(signal.name, "")) if mapping else ""
        subject_id = sid or subject
        session_id = session
        fnirs_id = f"{subject_id}::{session_id}"
        pair_id = fnirs_id
        role = (
            "subject_re"
            if signal.name.upper().endswith("_RE.TXT")
            else ("operator_op" if signal.name.upper().endswith("_OP.TXT") else "unknown")
        )
        names = [companion_pattern.format(stem=signal.stem, name=signal.name)]
        if signal.stem.upper().endswith("_RE"):
            names.append(companion_pattern.format(stem=signal.stem[:-3], name=signal.name))
        matches: list[Path] = []
        for name in names:
            matches.extend(signal.parent.glob(name))
        matches = list({p.resolve(): p for p in matches}.values())
        reason = ""
        status = "available"
        companion_path = ""
        if fnirs_id in seen_ids:
            status, reason = "excluded", "IDENTITY_CONFLICT"
        elif role not in allowed:
            status, reason = "excluded", "PROBE_ROLE_NOT_ALLOWED"
        elif len(matches) != 1:
            status, reason = "excluded", "COMPANION_MISSING" if not matches else "COMPANION_AMBIGUOUS"
        else:
            companion_path = matches[0].relative_to(base).as_posix()
        seen_ids.add(fnirs_id)
        companion_obj = matches[0] if companion_path else None
        out.append(
            {
                "subject_id": subject_id,
                "session_id": session_id,
                "fnirs_record_id": fnirs_id,
                "record_pair_id": pair_id,
                "probe_role": role,
                "signal_path": rel,
                "companion_csv_path": companion_path,
                "signal_size_bytes": signal.stat().st_size,
                "signal_sha256": _sha(signal),
                "companion_size_bytes": companion_obj.stat().st_size if companion_obj else "",
                "companion_sha256": _sha(companion_obj) if companion_obj else "",
                "status": status,
                "reason_code": reason,
                "expected_channel_count": expected_channel_count,
                "config_version": config_version,
            }
        )
    if fail_on_error:
        errors = [r for r in out if r["status"] != "available"]
        if errors:
            raise ValueError(f"processed-Hb manifest discovery failed: {len(errors)} record(s) excluded")
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fields = (
            list(out[0])
            if out
            else [
                "subject_id",
                "session_id",
                "fnirs_record_id",
                "record_pair_id",
                "probe_role",
                "signal_path",
                "companion_csv_path",
                "signal_size_bytes",
                "signal_sha256",
                "status",
                "reason_code",
            ]
        )
        with target.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(out)
    return out


def join_channel_annotation_table(
    channel_data: str | Path | Iterable[Mapping[str, Any]],
    channels: Iterable[Any],
    *,
    expected_channel_count: int | None = None,
    allowed_probe_roles: Iterable[str] = ("subject_re",),
    mapping_version: str = "",
) -> ChannelAnnotationTable:
    """Load and uniquely join channel annotations; fail closed on missing/duplicates."""
    required_fields = {
        "channel_id",
        "vendor_channel_number",
        "source_id",
        "detector_id",
        "source_detector_pair",
        "aal_label",
        "roi_label",
        "laterality",
        "localization_method",
        "mapping_source",
        "probe_role",
    }
    if isinstance(channel_data, (str, Path)):
        path = Path(channel_data)
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        digest = _sha(path)
    else:
        rows = [dict(r) for r in channel_data]
        digest = hashlib.sha256(repr(rows).encode()).hexdigest()
    def key(row: Mapping[str, Any]) -> str:
        return str(row.get("channel_id", row.get("vendor_channel_number", ""))).strip()
    index: dict[str, dict[str, Any]] = {}
    vendor_index: dict[str, dict[str, Any]] = {}
    vendor_numbers: set[str] = set()
    source_detector_pairs: set[str] = set()
    for source_row in rows:
        missing = [f for f in required_fields if not str(source_row.get(f, "")).strip()]
        coord_ok = all(str(source_row.get(k, "")).strip() for k in ("mni_x", "mni_y", "mni_z")) or all(
            str(source_row.get(k, "")).strip() for k in ("x", "y", "z")
        )
        if not coord_ok:
            missing.append("mni_x/mni_y/mni_z")
        if missing:
            raise ValueError(f"channel annotation missing required fields: {missing}")
        k = key(source_row)
        if not k or k in index:
            raise ValueError(f"duplicate or blank channel annotation: {k!r}")
        vendor_number = str(source_row["vendor_channel_number"]).strip()
        if vendor_number in vendor_numbers:
            raise ValueError(f"duplicate vendor channel number: {vendor_number!r}")
        pair = str(source_row["source_detector_pair"]).strip()
        if pair in source_detector_pairs:
            raise ValueError(f"duplicate source-detector pair: {pair!r}")
        index[k] = source_row
        vendor_index[vendor_number] = source_row
        vendor_numbers.add(vendor_number)
        source_detector_pairs.add(pair)
    names = [str(getattr(c, "channel", c)) for c in channels]
    if expected_channel_count is not None and len(names) != expected_channel_count:
        raise ValueError(f"expected {expected_channel_count} channels, observed {len(names)}")
    if expected_channel_count is not None and len(rows) != expected_channel_count:
        raise ValueError(f"expected {expected_channel_count} channel annotations, observed {len(rows)}")
    joined: list[dict[str, Any]] = []
    allowed = set(allowed_probe_roles)
    for i, name in enumerate(names, 1):
        row: dict[str, Any] | None = index.get(name)
        if row is None:
            row = vendor_index.get(str(i))
        if row is None:
            raise ValueError(f"missing channel annotation for {name}")
        role = row.get("probe_role", "subject_re")
        if role not in allowed:
            raise ValueError(f"probe role not allowed for channel {name}: {role}")
        item: dict[str, Any] = dict(row)
        item.setdefault("channel_id", name)
        item.setdefault("vendor_channel_number", i)
        item["mapping_sha256"] = digest
        item["mapping_version"] = str(item.get("mapping_version") or mapping_version)
        if not item["mapping_version"]:
            raise ValueError(f"mapping version is required for channel {name}")
        joined.append(item)
    if len({str(row["channel_id"]) for row in joined}) != len(names):
        raise ValueError("channel annotation join is not one-to-one")
    return ChannelAnnotationTable(tuple(joined), mapping_version, digest)
