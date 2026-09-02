"""Leakage-safe grouped regression utilities for processed-Hb M3/M4 studies.

The implementation is intentionally estimator-agnostic and keeps every
transform fold-local.  It supports continuous single- and multi-output
targets, output masks, LOSO outer folds and GroupKFold-style inner folds.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class FoldRecord:
    outer_test_groups: tuple[str, ...]
    outer_train_groups: tuple[str, ...]
    inner_folds: tuple[dict[str, Any], ...]
    predictions: np.ndarray
    target_mask: np.ndarray
    selected_alpha: float
    transform: dict[str, Any]
    beta: np.ndarray


def _groups(values: Sequence[Any] | np.ndarray) -> np.ndarray:
    g = np.asarray(values)
    if g.ndim != 1:
        raise ValueError("groups must be one-dimensional")
    if len(np.unique(g)) < 2:
        raise ValueError("at least two subject groups are required")
    return g.astype(str)


def _setting_for_group(value: Any, group: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(group)
    return value


def _fit_transform(
    X: np.ndarray,
    train: np.ndarray,
    test: np.ndarray,
    *,
    modality_groups: Sequence[str] | None = None,
    pca_components: int | Mapping[str, int] | None = None,
    pca_variance: float | Mapping[str, float] | None = None,
    feature_selection_k: int | None = None,
    y: np.ndarray | None = None,
    target_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Fit all preprocessing on ``train`` and apply it to ``test``.

    Median imputation and standardization are always fold-local. Optional PCA
    is fitted independently inside each declared modality, and optional
    univariate feature selection is fitted after PCA using training targets
    only. Modalities without a PCA setting pass through unchanged.
    """
    med = np.nanmedian(X[train], axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    tr = np.where(np.isfinite(X[train]), X[train], med)
    te = np.where(np.isfinite(X[test]), X[test], med)
    mean = tr.mean(axis=0)
    scale = tr.std(axis=0, ddof=1 if len(tr) > 1 else 0)
    scale = np.where(np.isfinite(scale) & (scale > 0), scale, 1.0)
    tr = (tr - mean) / scale
    te = (te - mean) / scale
    params: dict[str, Any] = {"median": med, "mean": mean, "scale": scale}
    if modality_groups is not None and len(modality_groups) != X.shape[1]:
        raise ValueError("modality_groups must have one value per feature")
    groups = list(map(str, modality_groups or ["all"] * X.shape[1]))
    ordered_groups = list(dict.fromkeys(groups))
    blocks = []
    tr_parts = []
    te_parts = []
    for group in ordered_groups:
        indices = np.asarray([index for index, value in enumerate(groups) if value == group], dtype=int)
        tr_block = tr[:, indices]
        te_block = te[:, indices]
        requested_components = _setting_for_group(pca_components, group)
        requested_variance = _setting_for_group(pca_variance, group)
        if requested_components is None and requested_variance is None:
            components = np.eye(len(indices), dtype=float)
            mode = "identity"
        else:
            _u, singular, vt = np.linalg.svd(tr_block, full_matrices=False)
            maximum = max(1, min(len(indices), len(train) - 1 if len(train) > 1 else 1, len(vt)))
            if requested_components is not None:
                count = min(maximum, max(1, int(requested_components)))
            else:
                threshold = float(requested_variance)
                if not 0 < threshold <= 1:
                    raise ValueError("pca_variance must be in (0, 1]")
                variance = singular**2
                if float(np.sum(variance)) <= 0:
                    count = 1
                else:
                    count = int(np.searchsorted(np.cumsum(variance) / np.sum(variance), threshold) + 1)
                    count = min(maximum, max(1, count))
            components = vt[:count].T
            mode = "pca"
        tr_parts.append(tr_block @ components)
        te_parts.append(te_block @ components)
        blocks.append(
            {
                "modality": group,
                "input_indices": indices,
                "components": components,
                "mode": mode,
            }
        )
    tr = np.column_stack(tr_parts)
    te = np.column_stack(te_parts)
    params["modality_groups"] = groups
    params["modality_blocks"] = blocks

    if feature_selection_k is not None:
        count = int(feature_selection_k)
        if count < 1:
            raise ValueError("feature_selection_k must be positive")
        count = min(count, tr.shape[1])
        scores = np.zeros(tr.shape[1], dtype=float)
        if y is not None:
            train_y = np.asarray(y[train], dtype=float)
            if train_y.ndim == 1:
                train_y = train_y[:, None]
            train_mask = (
                np.isfinite(train_y)
                if target_mask is None
                else np.asarray(target_mask[train], dtype=bool) & np.isfinite(train_y)
            )
            for feature_index in range(tr.shape[1]):
                output_scores = []
                for output_index in range(train_y.shape[1]):
                    valid = train_mask[:, output_index]
                    if np.sum(valid) < 2:
                        continue
                    x_values = tr[valid, feature_index]
                    y_values = train_y[valid, output_index]
                    if np.std(x_values) > 0 and np.std(y_values) > 0:
                        output_scores.append(abs(float(np.corrcoef(x_values, y_values)[0, 1])))
                scores[feature_index] = max(output_scores, default=0.0)
        # Stable ordering makes ties reproducible across NumPy versions.
        selected = np.asarray(sorted(range(len(scores)), key=lambda i: (-scores[i], i))[:count], dtype=int)
        tr = tr[:, selected]
        te = te[:, selected]
        params["feature_selection"] = {"selected_indices": selected, "scores": scores}
    return tr, te, params


def _apply_transform(X: np.ndarray, params: Mapping[str, Any]) -> np.ndarray:
    med = np.asarray(params["median"], dtype=float)
    mean = np.asarray(params["mean"], dtype=float)
    scale = np.asarray(params["scale"], dtype=float)
    values = np.where(np.isfinite(X), X, med)
    values = (values - mean) / scale
    blocks = params.get("modality_blocks")
    if blocks:
        values = np.column_stack(
            [
                values[:, np.asarray(block["input_indices"], dtype=int)]
                @ np.asarray(block["components"], dtype=float)
                for block in blocks
            ]
        )
    selection = params.get("feature_selection")
    if selection:
        values = values[:, np.asarray(selection["selected_indices"], dtype=int)]
    return values


def _group_hash(values: Sequence[Any] | np.ndarray) -> str:
    return hashlib.sha256(json.dumps(sorted(map(str, values)), separators=(",", ":")).encode()).hexdigest()


def _ridge_fit(X: np.ndarray, Y: np.ndarray, alpha: float) -> np.ndarray:
    if Y.ndim == 1:
        Y = Y[:, None]
    out = []
    for j in range(Y.shape[1]):
        valid = np.isfinite(Y[:, j])
        if not np.any(valid):
            out.append(np.zeros(X.shape[1]))
            continue
        xx = X[valid]
        yy = Y[valid, j]
        penalty = float(alpha) * np.eye(X.shape[1])
        penalty[0, 0] = 0.0  # never penalize the intercept
        out.append(np.linalg.solve(xx.T @ xx + penalty, xx.T @ yy))
    return np.column_stack(out)


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def nested_grouped_regression(
    X: Any,
    y: Any,
    groups: Sequence[Any] | np.ndarray,
    *,
    target_mask: Any = None,
    alphas: Sequence[float] = (1e-3, 1e-2, 1e-1, 1.0),
    inner_folds: int = 5,
    random_state: int | None = None,
    transform_observer: Callable[[str, np.ndarray, np.ndarray], None] | None = None,
    modality_groups: Sequence[str] | None = None,
    pca_components: int | Mapping[str, int] | None = None,
    pca_variance: float | Mapping[str, float] | None = None,
    feature_selection_k: int | None = None,
) -> dict[str, Any]:
    """Run outer Leave-One-Subject-Out with fold-local ridge preprocessing.

    Hyperparameters are selected by grouped inner validation using masked MAE.
    Returned predictions are complete OOF arrays; no target values are used in
    feature construction or imputation.
    """
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    if X.ndim != 2 or y.ndim not in (1, 2) or len(X) != len(y):
        raise ValueError("X/y dimensions are incompatible")
    if y.ndim == 1:
        y = y[:, None]
    g = _groups(groups)
    mask = np.ones_like(y, dtype=bool) if target_mask is None else np.asarray(target_mask, dtype=bool)
    if mask.shape != y.shape:
        raise ValueError("target_mask shape must match y")
    pred = np.full_like(y, np.nan, dtype=float)
    folds = []
    unique = np.unique(g)
    rng = np.random.default_rng(random_state) if random_state is not None else None
    for held in unique:
        test = np.flatnonzero(g == held)
        train = np.flatnonzero(g != held)
        train_groups = np.unique(g[train])
        k = min(int(inner_folds), len(train_groups))
        if k < 2:
            raise ValueError("inner grouped CV requires at least two training groups")
        inner = []
        alpha_errors: dict[float, list[float]] = {float(alpha): [] for alpha in alphas}
        fold_group_order = rng.permutation(train_groups) if rng is not None else train_groups
        for j in range(k):
            fold_groups = fold_group_order[np.arange(len(fold_group_order)) % k == j]
            val = np.flatnonzero(np.isin(g, fold_groups))
            tr = np.flatnonzero((g != held) & ~np.isin(g, fold_groups))
            val_group = ",".join(map(str, fold_groups))
            if transform_observer is not None:
                transform_observer("inner", tr.copy(), val.copy())
            Xt, Xv, params = _fit_transform(
                X,
                tr,
                val,
                modality_groups=modality_groups,
                pca_components=pca_components,
                pca_variance=pca_variance,
                feature_selection_k=feature_selection_k,
                y=y,
                target_mask=mask,
            )
            best = {"alpha": float("nan"), "mae": float("inf")}
            fold_scores = {}
            for alpha in alphas:
                alpha_value = float(alpha)
                beta = _ridge_fit(
                    np.column_stack([np.ones(len(Xt)), Xt]), np.where(mask[tr], y[tr], np.nan), float(alpha)
                )
                pv = np.column_stack([np.ones(len(Xv)), Xv]) @ beta
                valid = mask[val]
                mae = float(np.mean(np.abs(pv[valid] - y[val][valid]))) if np.any(valid) else float("inf")
                fold_scores[str(alpha_value)] = mae
                alpha_errors[alpha_value].append(mae)
                if mae < float(best["mae"]):
                    best = {"alpha": alpha_value, "mae": mae}
            inner.append(
                {
                    "validation_group": str(val_group),
                    "validation_groups": sorted(map(str, fold_groups)),
                    "train_groups": sorted(set(map(str, g[tr]))),
                    "validation_group_hash": _group_hash(fold_groups),
                    "train_group_hash": _group_hash(np.unique(g[tr])),
                    "best": best,
                    "alpha_mae": fold_scores,
                }
            )
        aggregate_alpha_mae = {
            alpha_value: float(np.mean(values)) if values else float("inf")
            for alpha_value, values in alpha_errors.items()
        }
        alpha = min(aggregate_alpha_mae, key=lambda value: (aggregate_alpha_mae[value], value))
        if transform_observer is not None:
            transform_observer("outer", train.copy(), test.copy())
        Xt, Xv, params = _fit_transform(
            X,
            train,
            test,
            modality_groups=modality_groups,
            pca_components=pca_components,
            pca_variance=pca_variance,
            feature_selection_k=feature_selection_k,
            y=y,
            target_mask=mask,
        )
        beta = _ridge_fit(np.column_stack([np.ones(len(Xt)), Xt]), np.where(mask[train], y[train], np.nan), alpha)
        pred[test] = np.column_stack([np.ones(len(Xv)), Xv]) @ beta
        folds.append(
            FoldRecord(
                tuple(map(str, [held])),
                tuple(map(str, train_groups)),
                tuple(inner),
                pred[test].copy(),
                mask[test].copy(),
                alpha,
                params,
                beta,
            )
        )
    valid = mask & np.isfinite(pred)
    mae = float(np.mean(np.abs(pred[valid] - y[valid]))) if np.any(valid) else float("nan")
    per_subject = []
    for subject in np.unique(g):
        subject_rows = g == subject
        subject_valid = valid[subject_rows]
        if np.any(subject_valid):
            errors = np.abs(pred[subject_rows] - y[subject_rows])
            per_subject.append(float(np.mean(errors[subject_valid])))
    subject_mae = float(np.mean(per_subject)) if per_subject else float("nan")
    return {
        "predictions": pred,
        "target_mask": mask,
        "mae": mae,
        "subject_weighted_mae": subject_mae,
        "folds": [
            {
                "outer_test_groups": f.outer_test_groups,
                "outer_train_groups": f.outer_train_groups,
                "outer_test_group_hash": _group_hash(f.outer_test_groups),
                "outer_train_group_hash": _group_hash(f.outer_train_groups),
                "inner_folds": f.inner_folds,
                "alpha": f.selected_alpha,
                "transform": _jsonable(f.transform),
                "beta": f.beta.tolist(),
            }
            for f in folds
        ],
        "fold_hash": hashlib.sha256(
            json.dumps(
                [{"test": f.outer_test_groups, "train": f.outer_train_groups} for f in folds], sort_keys=True
            ).encode()
        ).hexdigest(),
        "estimator": "ridge",
        "preprocessing": {
            "imputation": "fold_local_median",
            "standardization": "fold_local_zscore",
            "modality_pca": pca_components is not None or pca_variance is not None,
            "feature_selection": feature_selection_k,
        },
        "information_boundary": "subject-wise outer LOSO; fold-local transforms",
    }


def validate_information_boundary(
    feature_columns: Iterable[str | Mapping[str, Any]],
    *,
    forbidden: Iterable[str] = (),
    future_columns: Iterable[str] = (),
    task: str = "generic",
    prediction_time: float | None = None,
) -> None:
    """Reject target, future, canary and identity-proxy features by schema."""
    names = []
    bad = set()
    forbidden_names = set(map(str, forbidden)) | set(map(str, future_columns))
    for item in feature_columns:
        spec = dict(item) if isinstance(item, Mapping) else {"name": str(item)}
        name = str(spec.get("name", ""))
        names.append(name)
        kind = str(spec.get("kind", "feature")).casefold()
        available_at = spec.get("available_at")
        lowered = name.casefold()
        if name in forbidden_names or kind in {"target", "future", "canary", "id", "path", "date"}:
            bad.add(name)
        if any(token in lowered for token in ("canary", "future_", "__future", "file_path", "subject_id")):
            bad.add(name)
        if task.casefold() == "m3" and (kind == "vas" or "vas" in lowered):
            bad.add(name)
        if prediction_time is not None and available_at is not None and float(available_at) > prediction_time:
            bad.add(name)
        if task.casefold() == "m4" and kind in {"signal", "qc", "vas"}:
            try:
                is_future_step = float(spec.get("relative_step", 0)) > 0
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid relative_step for feature {name!r}") from exc
            if is_future_step:
                bad.add(name)
    cols = set(names)
    bad.update(cols & forbidden_names)
    if bad:
        raise ValueError(f"information boundary violation: {sorted(bad)}")
