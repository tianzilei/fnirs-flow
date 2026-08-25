from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class DesignBundle:
    model_id: str
    matrix: np.ndarray
    regressor_names: tuple[str, ...]
    design_hash: str
    rank: int
    condition_number: float
    residual_df: int
    diagnostics: dict[str, object]
    model_role: str = "confirmatory"
    nonestimable_columns: tuple[str, ...] = ()
    hash_payload: dict[str, object] | None = None


DESIGN_IMPLEMENTATION_VERSION = "processed_hb_design_v2"


def _canonical_events(events: list[object]) -> list[dict[str, object]]:
    selected = [e for e in events if getattr(e, "event_eligible", True) and not getattr(e, "duplicate_of_window", "")]
    return [
        {
            "duration": float(getattr(event, "duration")),
            "event_number": str(getattr(event, "event_number", "")),
            "event_time_layer": str(getattr(event, "event_time_layer", "")),
            "onset": float(getattr(event, "onset")),
            "trial_type": str(getattr(event, "trial_type", "")),
            "window_id": str(getattr(event, "window_id", "")),
        }
        for event in selected
    ]


def _time_axis_summary(timestamps_s: np.ndarray) -> dict[str, object]:
    values = np.ascontiguousarray(np.asarray(timestamps_s, dtype="<f8"))
    differences = np.diff(values)
    return {
        "count": int(values.size),
        "first_s": float(values[0]) if values.size else None,
        "last_s": float(values[-1]) if values.size else None,
        "median_dt_s": float(np.median(differences)) if differences.size else None,
        "timestamps_sha256": hashlib.sha256(values.tobytes(order="C")).hexdigest(),
    }


def _design_digest(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(serialized).hexdigest()


def _bundle(
    model_id: str,
    matrix: np.ndarray,
    names: list[str],
    diagnostics: dict[str, object] | None = None,
    *,
    timestamps_s: np.ndarray,
    events: list[object],
    design_parameters: dict[str, object],
) -> DesignBundle:
    matrix = np.asarray(matrix, dtype=float)
    canonical_matrix = np.ascontiguousarray(matrix, dtype="<f8")
    payload: dict[str, object] = {
        "basis_implementation_version": DESIGN_IMPLEMENTATION_VERSION,
        "contrast_definitions": [],
        "contrast_input_sha256": "",
        "design_parameters": design_parameters,
        "effective_events": _canonical_events(events),
        "matrix": {
            "dtype": "float64-le",
            "shape": list(canonical_matrix.shape),
            "sha256": hashlib.sha256(canonical_matrix.tobytes(order="C")).hexdigest(),
        },
        "model_id": model_id,
        "model_role": "confirmatory",
        "regressor_names": names,
        "regularized_time_axis": _time_axis_summary(timestamps_s),
    }
    digest = _design_digest(payload)
    rank = int(np.linalg.matrix_rank(matrix))
    nonestimable = tuple(names) if rank < matrix.shape[1] else ()
    return DesignBundle(
        model_id,
        matrix,
        tuple(names),
        digest,
        rank,
        float(np.linalg.cond(matrix)) if matrix.size else float("inf"),
        matrix.shape[0] - rank,
        diagnostics or {},
        "confirmatory",
        nonestimable,
        payload,
    )


def bind_design_contrasts(
    bundle: DesignBundle,
    definitions: list[dict[str, Any]],
    *,
    contrast_input_sha256: str,
) -> DesignBundle:
    """Return a bundle whose hash binds normalized, ordered contrast definitions."""
    payload = dict(bundle.hash_payload or {})
    payload["contrast_definitions"] = [
        {
            "component_names": list(definition["component_names"]),
            "contrast_id": str(definition["contrast_id"]),
            "weights": np.asarray(definition["weights"], dtype=float).tolist(),
        }
        for definition in definitions
    ]
    payload["contrast_input_sha256"] = contrast_input_sha256
    return DesignBundle(
        model_id=bundle.model_id,
        matrix=bundle.matrix,
        regressor_names=bundle.regressor_names,
        design_hash=_design_digest(payload),
        rank=bundle.rank,
        condition_number=bundle.condition_number,
        residual_df=bundle.residual_df,
        diagnostics=bundle.diagnostics,
        model_role=bundle.model_role,
        nonestimable_columns=bundle.nonestimable_columns,
        hash_payload=payload,
    )


def compile_condition_glm(timestamps_s: np.ndarray, events: list[object], *, hrf_model: str = "glover") -> DesignBundle:
    from fnirs_flow.adapters.mne_nirs_analysis import _canonical_hrf

    t = np.asarray(timestamps_s, dtype=float)
    dt = float(np.median(np.diff(t)))
    sfreq = 1 / dt
    hrf = _canonical_hrf(sfreq, hrf_model)
    cols: list[np.ndarray] = []
    names: list[str] = []
    selected = [e for e in events if getattr(e, "event_eligible", True) and not getattr(e, "duplicate_of_window", "")]
    labels = [str(getattr(e, "trial_type", "")) for e in selected]
    if not labels or any(not label for label in labels) or len(set(labels)) != len(labels):
        raise ValueError("Condition GLM requires non-empty, unique trial_type labels")
    for i, e in enumerate(selected, 1):
        stim = ((t >= float(e.onset)) & (t < float(e.onset) + float(e.duration))).astype(float)
        conv = np.convolve(stim, hrf, mode="full")[: len(t)]
        deriv = np.gradient(conv)
        condition = str(getattr(e, "trial_type", "") or f"condition_{i}")
        cols += [conv, deriv]
        names += [f"{condition}__canonical", f"{condition}__temporal_derivative"]
    x = np.column_stack(cols) if cols else np.empty((len(t), 0))
    x = np.column_stack([x, np.ones(len(t))])
    names.append("constant")
    parameters = {"basis": "canonical_hrf_with_temporal_derivative", "hrf_model": hrf_model}
    return _bundle(
        "glm_conditions_canonical_td_v1",
        x,
        names,
        {**parameters, "n_events": len(selected)},
        timestamps_s=t,
        events=events,
        design_parameters=parameters,
    )


def compile_post_event_fir(
    timestamps_s: np.ndarray,
    events: list[object],
    *,
    bins: tuple[tuple[float, float], ...] = ((0, 10), (10, 20), (20, 30)),
) -> DesignBundle:
    t = np.asarray(timestamps_s, dtype=float)
    cols = []
    names = []
    selected = [e for e in events if getattr(e, "event_eligible", True) and not getattr(e, "duplicate_of_window", "")]
    for start, stop in bins:
        pooled = np.zeros(len(t))
        for e in selected:
            offset = float(e.onset) + float(e.duration)
            pooled += ((t >= offset + start) & (t < offset + stop)).astype(float)
        cols.append(pooled)
        names.append(f"offset__{start:g}_{stop:g}s")
    x = np.column_stack(cols) if cols else np.empty((len(t), 0))
    x = np.column_stack([x, np.ones(len(t))])
    names.append("constant")
    return _bundle(
        "fir_post_event_0_30_10s_v1",
        x,
        names,
        {"bins": [list(b) for b in bins], "offset_0_30_weights": [1 / 3, 1 / 3, 1 / 3]},
        timestamps_s=t,
        events=events,
        design_parameters={"basis": "piecewise_constant_fir", "bins": [list(b) for b in bins]},
    )


def compile_event_order_glm(timestamps_s: np.ndarray, events: list[object]) -> DesignBundle:
    t = np.asarray(timestamps_s, float)
    selected = [e for e in events if getattr(e, "event_eligible", True) and not getattr(e, "duplicate_of_window", "")]
    if len(selected) < 2:
        raise ValueError("Event-order GLM requires at least two eligible events")
    numbers = [str(getattr(e, "event_number", "")) for e in selected]
    if all(numbers) and numbers != sorted(numbers, key=lambda value: int(value)):
        raise ValueError("GLM-TREND event_number conflicts with frozen event order")
    cols = []
    names = []
    stim = np.zeros(len(t))
    for e in selected:
        stim += ((t >= e.onset) & (t < e.onset + e.duration)).astype(float)
    dt = float(np.median(np.diff(t)))
    from fnirs_flow.adapters.mne_nirs_analysis import _canonical_hrf

    hrf = _canonical_hrf(1 / dt, "glover")
    main = np.convolve(stim, hrf, mode="full")[: len(t)]
    cols.extend([main, np.gradient(main)])
    names.extend(["events__canonical", "events__temporal_derivative"])
    scores = tuple(float(value) for value in np.linspace(-1.0, 1.0, len(selected)))
    modulation = np.zeros(len(t))
    for idx, e in enumerate(selected):
        pulse = ((t >= e.onset) & (t < e.onset + e.duration)).astype(float)
        modulation += pulse * scores[min(idx, len(scores) - 1)]
    mod = np.convolve(modulation, hrf, mode="full")[: len(t)]
    cols.extend([mod, np.gradient(mod)])
    names.extend(["event_order__linear_modulation__canonical", "event_order__linear_modulation__temporal_derivative"])
    x = np.column_stack(cols) if cols else np.empty((len(t), 0))
    x = np.column_stack([x, np.ones(len(t))])
    names.append("constant")
    parameters = {
        "basis": "canonical_hrf_with_temporal_derivative",
        "hrf_model": "glover",
        "trend_scores": list(scores),
    }
    return _bundle(
        "glm_event_order_linear_canonical_td_v1",
        x,
        names,
        parameters,
        timestamps_s=t,
        events=events,
        design_parameters=parameters,
    )
