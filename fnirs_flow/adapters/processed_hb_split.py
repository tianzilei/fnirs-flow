"""Channel/time splitting and format export for NIRS-SPM processed-Hb data."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np


@dataclass(frozen=True)
class SplitProcessedHb:
    """A view of a processed-Hb recording after channel/time selection."""

    time_s: np.ndarray
    hbo: np.ndarray
    hbr: np.ndarray
    hbt: np.ndarray
    channel_names: tuple[str, ...]
    task: tuple[str, ...]
    mark: tuple[str, ...]
    count: tuple[str, ...]
    source_path: str = ""
    source_provenance: dict[str, Any] | None = None
    channel_indices: tuple[int, ...] = ()
    time_window_s: tuple[float, float] | None = None

    @property
    def n_samples(self) -> int:
        return int(self.time_s.size)

    @property
    def n_channels(self) -> int:
        return len(self.channel_names)


def split_processed_hb(
    data: Any,
    *,
    channels: Iterable[str | int] | None = None,
    time_window_s: tuple[float, float] | None = None,
) -> SplitProcessedHb:
    """Split a validated processed-Hb recording.

    Both the public ``ProcessedHbRecording`` contract and the legacy private
    reader object are accepted through structural attribute inspection.  This
    keeps the public adapter independent from development-only modules.
    """

    if hasattr(data, "native_timestamps_s"):
        time_s = np.asarray(data.native_timestamps_s, dtype=float)
        hbo = np.asarray(data.hbo, dtype=float).T
        hbr = np.asarray(data.hbr, dtype=float).T
        hbt_source = data.hbt_validation
        hbt = hbo + hbr if hbt_source is None else np.asarray(hbt_source, dtype=float).T
        names = [channel.channel for channel in data.channels]
        task_values = data.task_values
        mark_values = data.mark_values
        count_values = data.count_values
        provenance_value = data.provenance
        provenance = (
            asdict(cast(Any, provenance_value))
            if is_dataclass(provenance_value)
            else dict(provenance_value)
        )
        source_path = str(provenance.get("local_path", ""))
    else:
        required = ("time_s", "hbo", "hbr", "hbt", "channel_names", "task", "mark", "count")
        missing = [name for name in required if not hasattr(data, name)]
        if missing:
            raise TypeError(f"processed-Hb input is missing required attributes: {', '.join(missing)}")
        time_s = np.asarray(data.time_s, dtype=float)
        hbo = np.asarray(data.hbo, dtype=float)
        hbr = np.asarray(data.hbr, dtype=float)
        hbt = np.asarray(data.hbt, dtype=float)
        names = [str(name) for name in data.channel_names]
        task_values = data.task
        mark_values = data.mark
        count_values = data.count
        provenance = dict(getattr(data, "provenance", {}) or {})
        source_path = str(getattr(data, "path", ""))

    expected_shape = (time_s.size, len(names))
    if time_s.ndim != 1 or any(array.shape != expected_shape for array in (hbo, hbr, hbt)):
        raise ValueError("processed-Hb arrays must be sample x channel and align with timestamps/channel names")

    def normalized_labels(values: Any, label: str) -> tuple[str, ...]:
        if values is None:
            return ("",) * time_s.size
        labels = tuple(str(value) for value in values)
        if len(labels) != time_s.size:
            raise ValueError(f"{label} values must align with timestamps")
        return labels

    task = normalized_labels(task_values, "task")
    mark = normalized_labels(mark_values, "mark")
    count = normalized_labels(count_values, "count")

    if channels is None:
        indices = list(range(len(names)))
    else:
        indices = []
        for item in channels:
            if isinstance(item, int):
                idx = item - 1
                if idx < 0 or idx >= len(names):
                    raise ValueError(f"channel number out of range: {item}")
            else:
                value = str(item).strip().casefold()
                matches = [i for i, name in enumerate(names) if name.casefold() == value]
                if not matches:
                    raise ValueError(f"unknown channel: {item}")
                idx = matches[0]
            if idx not in indices:
                indices.append(idx)
    if not indices:
        raise ValueError("at least one channel is required")

    mask = np.ones(time_s.shape, dtype=bool)
    window = None
    if time_window_s is not None:
        if len(time_window_s) != 2 or time_window_s[1] < time_window_s[0]:
            raise ValueError("time_window_s must be (start_s, end_s) with end >= start")
        start, end = float(time_window_s[0]), float(time_window_s[1])
        mask = (time_s >= start) & (time_s <= end)
        if not np.any(mask):
            raise ValueError(f"time window contains no samples: {time_window_s}")
        window = (start, end)
    return SplitProcessedHb(
        time_s=np.asarray(time_s[mask], dtype=float),
        hbo=np.asarray(hbo[mask][:, indices], dtype=float),
        hbr=np.asarray(hbr[mask][:, indices], dtype=float),
        hbt=np.asarray(hbt[mask][:, indices], dtype=float),
        channel_names=tuple(names[i] for i in indices),
        task=tuple(task[i] for i in np.flatnonzero(mask)),
        mark=tuple(mark[i] for i in np.flatnonzero(mask)),
        count=tuple(count[i] for i in np.flatnonzero(mask)),
        source_path=source_path,
        source_provenance=provenance,
        channel_indices=tuple(i + 1 for i in indices),
        time_window_s=window,
    )


def save_split_processed_hb(split: SplitProcessedHb, path: str | Path, *, fmt: str | None = None) -> Path:
    """Save a split recording as ``txt``/``csv``, ``json`` or compressed ``npz``."""

    target = Path(path)
    format_name = (fmt or target.suffix.lstrip(".") or "csv").casefold()
    if format_name in {"txt", "tsv", "csv"}:
        delimiter = "\t" if format_name in {"txt", "tsv"} else ","
        fields = ["Time(sec)", "Task", "Mark", "Count"]
        for name in split.channel_names:
            fields.extend([f"{name} oxyHb", f"{name} deoxyHb", f"{name} totalHb"])
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream, delimiter=delimiter)
            writer.writerow(fields)
            for row in range(split.n_samples):
                values: list[Any] = [split.time_s[row], split.task[row], split.mark[row], split.count[row]]
                for col in range(split.n_channels):
                    values.extend([split.hbo[row, col], split.hbr[row, col], split.hbt[row, col]])
                writer.writerow(values)
    elif format_name == "json":
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": "processed_hb_split_v1",
            "source_path": split.source_path,
            "channel_names": list(split.channel_names),
            "channel_indices": list(split.channel_indices),
            "time_window_s": split.time_window_s,
            "time_s": split.time_s.tolist(),
            "hbo": split.hbo.tolist(),
            "hbr": split.hbr.tolist(),
            "hbt": split.hbt.tolist(),
            "task": list(split.task),
            "mark": list(split.mark),
            "count": list(split.count),
            "source_provenance": split.source_provenance or {},
        }
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    elif format_name == "npz":
        target.parent.mkdir(parents=True, exist_ok=True)
        # Passing a string/path makes NumPy append ``.npz`` when the supplied
        # name has another suffix.  Write through a file handle so the path
        # returned by this function is always the path actually created.
        with target.open("wb") as stream:
            np.savez_compressed(
                stream,
                time_s=split.time_s,
                hbo=split.hbo,
                hbr=split.hbr,
                hbt=split.hbt,
                channel_names=np.asarray(split.channel_names),
                channel_indices=np.asarray(split.channel_indices, dtype=int),
                task=np.asarray(split.task),
                mark=np.asarray(split.mark),
                count=np.asarray(split.count),
                source_path=np.asarray(split.source_path),
                source_provenance_json=np.asarray(json.dumps(split.source_provenance or {}, ensure_ascii=False)),
                time_window_s=np.asarray(split.time_window_s or (), dtype=float),
            )
    else:
        raise ValueError(f"unsupported split output format: {format_name}")
    return target
