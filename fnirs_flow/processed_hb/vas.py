"""Project-level continuous VAS M0/M3/M0-AR/M4 evaluation."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import platform
import sys
from collections.abc import Mapping, Sequence
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np

from .ml import _apply_transform, nested_grouped_regression, validate_information_boundary

MODEL_IDS = ("M0-static", "M3", "M0-AR", "M4", "naive_persistence")
MIN_PERMUTATIONS = 10_000
MIN_BOOTSTRAPS = 2_000


def _canonical_json(value: Any) -> str:
    def normalize(item: Any) -> Any:
        if isinstance(item, np.ndarray):
            return item.tolist()
        if isinstance(item, np.generic):
            return item.item()
        if isinstance(item, Mapping):
            return {str(key): normalize(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalize(child) for child in item]
        if isinstance(item, float) and not np.isfinite(item):
            return None
        return item

    return json.dumps(normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_json(path: Path, value: Any) -> Path:
    path.write_text(_canonical_json(value), encoding="utf-8")
    return path


def _write_csv_gz(path: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    fields = list(rows[0]) if rows else []
    with gzip.open(path, "wt", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        if fields:
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
    return path


def write_continuous_vas_derivatives(outdir: str | Path, result: Mapping[str, Any]) -> dict[str, str]:
    """Write the complete project VAS audit bundle and its content hashes."""
    comparisons = result.get("comparisons", {})
    resampling_valid = result.get("resampling_standard_met") is True and all(
        comparison.get("permutation", {}).get("n", 0) >= MIN_PERMUTATIONS
        and comparison.get("cluster_bootstrap", {}).get("n", 0) >= MIN_BOOTSTRAPS
        for comparison in comparisons.values()
    )
    if not comparisons or not resampling_valid:
        raise ValueError("FORMAL_DERIVATIVE_RESAMPLING_STANDARD_NOT_MET")
    provenance = result.get("provenance", {})
    required_provenance = (
        "software_version",
        "python",
        "dependency_versions",
        "git_commit",
        "execution_command",
        "input_sha256",
    )
    missing_provenance = [
        key
        for key in required_provenance
        if not provenance.get(key)
    ]
    if missing_provenance:
        raise ValueError(f"FORMAL_DERIVATIVE_PROVENANCE_MISSING: {', '.join(missing_provenance)}")
    root = Path(outdir)
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "oof_predictions": _write_csv_gz(root / "continuous_vas_oof_predictions.csv.gz", result["oof_predictions"]),
        "metrics": _write_json(root / "continuous_vas_metrics.json", result["metrics"]),
        "comparisons": _write_json(root / "continuous_vas_comparisons.json", result["comparisons"]),
        "folds": _write_json(root / "continuous_vas_folds.json", result["folds"]),
        "recursive_sensitivity": _write_json(
            root / "continuous_vas_recursive_sensitivity.json", result["m4_recursive_sensitivity"]
        ),
        "duplicate_audit": _write_json(root / "continuous_vas_duplicate_audit.json", result["duplicate_audit"]),
    }
    artifact_hashes = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths.values()
    }
    manifest = {
        "schema_version": "1.0.0",
        "config_hash": result["config_hash"],
        "model_ids": result["model_ids"],
        "resampling_standard_met": result["resampling_standard_met"],
        "information_boundary": result["information_boundary"],
        "provenance": result["provenance"],
        "artifact_sha256": artifact_hashes,
    }
    manifest_path = _write_json(root / "continuous_vas_manifest.json", manifest)
    return {**{key: str(path) for key, path in paths.items()}, "manifest": str(manifest_path)}


def _duplicate_record_audit(
    subjects: np.ndarray,
    records: np.ndarray,
    static: np.ndarray,
    physiology: np.ndarray,
) -> dict[str, Any]:
    signatures: dict[str, list[tuple[str, str]]] = {}
    for index, (subject, record) in enumerate(zip(subjects, records, strict=True)):
        payload = np.concatenate([static[index].ravel(), physiology[index].ravel()])
        normalized = np.where(np.isnan(payload), np.inf, payload).astype("<f8", copy=False)
        signature = hashlib.sha256(normalized.tobytes()).hexdigest()
        signatures.setdefault(signature, []).append((str(subject), str(record)))
    duplicates = [
        {"feature_sha256": digest, "records": values, "cross_subject": len({value[0] for value in values}) > 1}
        for digest, values in signatures.items()
        if len(values) > 1
    ]
    return {
        "record_count": len(records),
        "exact_feature_duplicates": duplicates,
        "cross_subject_duplicate_count": sum(bool(item["cross_subject"]) for item in duplicates),
        "near_duplicate_policy": "not_inferred; exact IEEE-754 feature identity only",
    }


def _subject_mae(errors: np.ndarray, subjects: np.ndarray, mask: np.ndarray) -> float:
    values = []
    for subject in np.unique(subjects):
        selected = (subjects == subject)[:, None] & mask & np.isfinite(errors)
        if np.any(selected):
            values.append(float(np.mean(errors[selected])))
    return float(np.mean(values)) if values else float("nan")


def _permutation_delta(
    errors_a: np.ndarray,
    errors_b: np.ndarray,
    subjects: np.ndarray,
    mask: np.ndarray,
    *,
    n_permutations: int,
    rng: np.random.Generator,
) -> dict[str, float | int]:
    observed = _subject_mae(errors_a, subjects, mask) - _subject_mae(errors_b, subjects, mask)
    exceed = 0
    unique = np.unique(subjects)
    for _ in range(n_permutations):
        swap = {subject: bool(rng.integers(0, 2)) for subject in unique}
        pa = errors_a.copy()
        pb = errors_b.copy()
        for subject in unique:
            if swap[subject]:
                selected = subjects == subject
                pa[selected], pb[selected] = errors_b[selected], errors_a[selected]
        permuted = _subject_mae(pa, subjects, mask) - _subject_mae(pb, subjects, mask)
        exceed += abs(permuted) >= abs(observed)
    return {"observed_delta_mae": observed, "p_value": (exceed + 1) / (n_permutations + 1), "n": n_permutations}


def _cluster_bootstrap(
    errors_a: np.ndarray,
    errors_b: np.ndarray,
    subjects: np.ndarray,
    mask: np.ndarray,
    *,
    n_bootstrap: int,
    rng: np.random.Generator,
) -> dict[str, float | int]:
    unique = np.unique(subjects)
    deltas = []
    for _ in range(n_bootstrap):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        subject_deltas = []
        for subject in sampled:
            selected = (subjects == subject)[:, None] & mask & np.isfinite(errors_a) & np.isfinite(errors_b)
            if np.any(selected):
                subject_deltas.append(float(np.mean(errors_a[selected]) - np.mean(errors_b[selected])))
        if subject_deltas:
            deltas.append(float(np.mean(subject_deltas)))
    return {
        "ci_low": float(np.quantile(deltas, 0.025)),
        "ci_high": float(np.quantile(deltas, 0.975)),
        "n": n_bootstrap,
    }


def _same_evaluation_mask(a: np.ndarray, b: np.ndarray) -> None:
    if not np.array_equal(a, b):
        raise ValueError("BASELINE_EVALUATION_MASK_MISMATCH")


def _array_hash(value: np.ndarray) -> str:
    array = np.ascontiguousarray(value)
    payload = f"{array.dtype.str}|{array.shape}".encode("ascii") + array.tobytes()
    return hashlib.sha256(payload).hexdigest()


def run_continuous_vas_models(
    *,
    subject_ids: Sequence[Any],
    window_ids: Sequence[str],
    vas: Any,
    target_mask: Any,
    static_features: Any,
    physiology_features: Any,
    static_feature_schema: Sequence[str | Mapping[str, Any]],
    physiology_feature_schema: Sequence[str | Mapping[str, Any]],
    record_ids: Sequence[Any] | None = None,
    vas_min: float = 0.0,
    vas_max: float = 10.0,
    inner_folds: int = 5,
    n_permutations: int = 10_000,
    n_bootstrap: int = 2_000,
    random_seed: int = 0,
    modality_pca_variance: float = 0.95,
    feature_selection_k: int | None = None,
    minimum_gain_mae: float | None = None,
    gain_alpha: float | None = None,
    input_sha256: str = "",
    git_commit: str = "",
    execution_command: str = "",
    evaluation_mask_schema: Mapping[str, Any] | None = None,
    allow_reduced_resampling_for_testing: bool = False,
    outdir: str | Path | None = None,
) -> dict[str, Any]:
    """Generate leakage-safe continuous OOF predictions for all project models.

    Rows are subject records and columns are ordered VAS windows. M3 reconstructs
    the full trajectory from static + same-window physiology. M4 predicts t+1
    from information available at t; missing history is represented by value
    plus mask and recursive chains never restart after interruption.
    """
    subjects = np.asarray(subject_ids).astype(str)
    windows = list(map(str, window_ids))
    y = np.asarray(vas, dtype=float)
    mask = np.asarray(target_mask, dtype=bool)
    static = np.asarray(static_features, dtype=float)
    physiology = np.asarray(physiology_features, dtype=float)
    if y.ndim != 2 or y.shape != mask.shape or len(subjects) != len(y):
        raise ValueError("VAS_SHAPE_INVALID")
    if y.shape[1] != len(windows) or static.ndim != 2 or len(static) != len(y):
        raise ValueError("VAS_FEATURE_SHAPE_INVALID")
    if physiology.ndim == 2:
        physiology = np.repeat(physiology[:, None, :], len(windows), axis=1)
    if physiology.ndim != 3 or physiology.shape[:2] != y.shape:
        raise ValueError("PHYSIOLOGY_FEATURE_SHAPE_INVALID")
    mask = mask & np.isfinite(y)
    records = np.asarray(record_ids if record_ids is not None else [f"row-{i}" for i in range(len(y))]).astype(str)
    if len(records) != len(y) or len(set(records)) != len(records):
        raise ValueError("RECORD_ID_NOT_UNIQUE")
    if outdir is not None and record_ids is None:
        raise ValueError("RECORD_IDS_REQUIRED_FOR_PROJECT_DERIVATIVES")
    validate_information_boundary(static_feature_schema, task="m3")
    validate_information_boundary(physiology_feature_schema, task="m3")
    validate_information_boundary(static_feature_schema, task="m4", prediction_time=0.0)
    validate_information_boundary(physiology_feature_schema, task="m4", prediction_time=0.0)
    if n_permutations < 1 or n_bootstrap < 1:
        raise ValueError("STATISTICAL_RESAMPLE_COUNT_INVALID")
    standard_met = n_permutations >= MIN_PERMUTATIONS and n_bootstrap >= MIN_BOOTSTRAPS
    if not standard_met and not allow_reduced_resampling_for_testing:
        raise ValueError("STATISTICAL_RESAMPLE_COUNT_BELOW_PROJECT_MINIMUM")
    if outdir is not None and allow_reduced_resampling_for_testing:
        raise ValueError("REDUCED_RESAMPLING_CANNOT_WRITE_PROJECT_DERIVATIVES")
    if outdir is not None:
        required_identity = {
            "input_sha256": input_sha256,
            "git_commit": git_commit,
            "execution_command": execution_command,
        }
        missing_identity = [key for key, value in required_identity.items() if not str(value).strip()]
        if missing_identity:
            raise ValueError(f"PROJECT_DERIVATIVE_IDENTITY_MISSING: {', '.join(missing_identity)}")
        input_hash = str(input_sha256).lower()
        commit_hash = str(git_commit).lower()
        if len(input_hash) != 64 or any(character not in "0123456789abcdef" for character in input_hash):
            raise ValueError("PROJECT_DERIVATIVE_IDENTITY_INVALID: input_sha256")
        if len(commit_hash) not in {40, 64} or any(character not in "0123456789abcdef" for character in commit_hash):
            raise ValueError("PROJECT_DERIVATIVE_IDENTITY_INVALID: git_commit")
    if minimum_gain_mae is not None and float(minimum_gain_mae) < 0:
        raise ValueError("MINIMUM_GAIN_MAE_INVALID")
    if gain_alpha is not None and not 0 < float(gain_alpha) < 1:
        raise ValueError("GAIN_ALPHA_INVALID")
    mask_sources = set(map(str, (evaluation_mask_schema or {}).get("sources", [])))
    forbidden_mask_sources = mask_sources & {
        "target_signal",
        "target_qc",
        "prediction_error",
        "future_signal",
        "future_qc",
    }
    if not mask_sources or forbidden_mask_sources:
        raise ValueError("EVALUATION_MASK_INFORMATION_BOUNDARY_INVALID")
    duplicate_audit = _duplicate_record_audit(subjects, records, static, physiology)
    if duplicate_audit["cross_subject_duplicate_count"]:
        raise ValueError("CROSS_SUBJECT_EXACT_FEATURE_DUPLICATE")

    n, n_windows = y.shape
    # One row is one record-window. M3 receives only physiology from that same
    # window; flattening all windows into one subject row would leak later
    # signals into earlier targets. The known window index is present in both
    # M0-static and M3 so their comparison remains fair.
    flat_subjects = np.repeat(subjects, n_windows)
    flat_static = np.repeat(static, n_windows, axis=0)
    flat_window = np.tile(np.arange(n_windows, dtype=float), n)[:, None]
    flat_target = y.reshape(-1)
    flat_mask = mask.reshape(-1)
    m0_features = np.column_stack([flat_static, flat_window])
    m3_features = np.column_stack([flat_static, flat_window, physiology.reshape(n * n_windows, -1)])
    static_modalities = ["static"] * static.shape[1] + ["design"]
    physiology_modalities = [
        str(dict(item).get("modality", "physiology")) if isinstance(item, Mapping) else "physiology"
        for item in physiology_feature_schema
    ]
    m0 = nested_grouped_regression(
        m0_features,
        flat_target,
        flat_subjects,
        target_mask=flat_mask[:, None],
        inner_folds=inner_folds,
        modality_groups=static_modalities,
    )
    m3 = nested_grouped_regression(
        m3_features,
        flat_target,
        flat_subjects,
        target_mask=flat_mask[:, None],
        inner_folds=inner_folds,
        modality_groups=static_modalities + physiology_modalities,
        pca_variance={group: modality_pca_variance for group in set(physiology_modalities)},
        feature_selection_k=feature_selection_k,
    )
    _same_evaluation_mask(m0["target_mask"], m3["target_mask"])

    ar_rows = []
    ar_targets = []
    ar_masks = []
    ar_subjects = []
    ar_window_index = []
    for row in range(n):
        for target_window in range(1, n_windows):
            history_available = bool(mask[row, target_window - 1] and np.isfinite(y[row, target_window - 1]))
            history_value = float(y[row, target_window - 1]) if history_available else 0.0
            base = np.concatenate([static[row], [history_value, float(history_available), target_window]])
            ar_rows.append(base)
            ar_targets.append(y[row, target_window])
            ar_masks.append(mask[row, target_window])
            ar_subjects.append(subjects[row])
            ar_window_index.append((row, target_window))
    ar_x = np.asarray(ar_rows, dtype=float)
    ar_y = np.asarray(ar_targets, dtype=float)
    ar_mask = np.asarray(ar_masks, dtype=bool)
    ar_groups = np.asarray(ar_subjects)
    m0_ar = nested_grouped_regression(
        ar_x,
        ar_y,
        ar_groups,
        target_mask=ar_mask[:, None],
        inner_folds=inner_folds,
        modality_groups=["static"] * static.shape[1] + ["history", "history", "design"],
    )
    m4_x = np.column_stack(
        [ar_x, np.asarray([physiology[row, target - 1] for row, target in ar_window_index], dtype=float)]
    )
    m4 = nested_grouped_regression(
        m4_x,
        ar_y,
        ar_groups,
        target_mask=ar_mask[:, None],
        inner_folds=inner_folds,
        modality_groups=["static"] * static.shape[1]
        + ["history", "history", "design"]
        + physiology_modalities,
        pca_variance={group: modality_pca_variance for group in set(physiology_modalities)},
        feature_selection_k=feature_selection_k,
    )
    _same_evaluation_mask(m0_ar["target_mask"], m4["target_mask"])

    recursive_prediction = np.full((n, n_windows), np.nan, dtype=float)
    recursive_chain_active = np.zeros((n, n_windows), dtype=bool)
    m4_fold_by_subject = {fold["outer_test_groups"][0]: fold for fold in m4["folds"]}
    for row, subject in enumerate(subjects):
        fold = m4_fold_by_subject[subject]
        transform = fold["transform"]
        beta = np.asarray(fold["beta"], dtype=float)
        active = bool(mask[row, 0] and np.isfinite(y[row, 0]))
        previous = float(y[row, 0]) if active else 0.0
        for target_window in range(1, n_windows):
            if not active:
                continue
            features = np.concatenate(
                [
                    static[row],
                    [previous, 1.0, target_window],
                    physiology[row, target_window - 1],
                ]
            )[None, :]
            standardized = _apply_transform(features, transform)
            predicted = float((np.column_stack([np.ones(1), standardized]) @ beta).item())
            recursive_prediction[row, target_window] = predicted
            recursive_chain_active[row, target_window] = True
            previous = predicted
            # A missing/invalid immediately preceding input window interrupts
            # the chain permanently; later observed VAS can never restart it.
            if not mask[row, target_window]:
                active = False

    naive = np.asarray([row[-3] if row[-2] else np.nan for row in ar_x], dtype=float)[:, None]
    m0_ar_pred = np.asarray(m0_ar["predictions"], dtype=float)
    m4_pred = np.asarray(m4["predictions"], dtype=float)
    static_pred = np.asarray(m0["predictions"], dtype=float).reshape(n, n_windows)
    m3_pred = np.asarray(m3["predictions"], dtype=float).reshape(n, n_windows)

    prediction_rows = []
    model_arrays = {
        "M0-static": (static_pred, y, mask, subjects, [(i, j) for i in range(n) for j in range(n_windows)]),
        "M3": (m3_pred, y, mask, subjects, [(i, j) for i in range(n) for j in range(n_windows)]),
        "M0-AR": (m0_ar_pred, ar_y[:, None], ar_mask[:, None], ar_groups, ar_window_index),
        "M4": (m4_pred, ar_y[:, None], ar_mask[:, None], ar_groups, ar_window_index),
        "naive_persistence": (naive, ar_y[:, None], ar_mask[:, None], ar_groups, ar_window_index),
    }
    metrics = {}
    for model_id, (prediction, target, evaluation_mask, groups, indices) in model_arrays.items():
        clipped = np.clip(prediction, vas_min, vas_max)
        correction = np.isfinite(prediction) & (prediction != clipped)
        errors = np.abs(clipped - target)
        metrics[model_id] = {
            "subject_equal_mae": _subject_mae(errors, groups, evaluation_mask),
            "evaluated_values": int(np.sum(evaluation_mask & np.isfinite(prediction))),
        }
        for flat_index, (subject_row, window_index) in enumerate(indices):
            column = window_index if prediction.shape[1] > 1 else 0
            prediction_rows.append(
                {
                    "model_id": model_id,
                    "subject_id": subjects[subject_row],
                    "record_id": records[subject_row],
                    "window_id": windows[window_index],
                    "target": float(target[subject_row, window_index])
                    if target.shape == y.shape
                    else float(target[flat_index, 0]),
                    "evaluation_mask": bool(evaluation_mask[subject_row, window_index])
                    if evaluation_mask.shape == y.shape
                    else bool(evaluation_mask[flat_index, 0]),
                    "prediction_raw": float(prediction[subject_row, column])
                    if prediction.shape[0] == n
                    else float(prediction[flat_index, 0]),
                    "prediction_clipped": float(clipped[subject_row, column])
                    if prediction.shape[0] == n
                    else float(clipped[flat_index, 0]),
                    "range_corrected": bool(correction[subject_row, column])
                    if prediction.shape[0] == n
                    else bool(correction[flat_index, 0]),
                }
            )

    rng = np.random.default_rng(random_seed)
    static_errors = np.abs(np.clip(static_pred, vas_min, vas_max) - y)
    m3_errors = np.abs(np.clip(m3_pred, vas_min, vas_max) - y)
    ar_errors = np.abs(np.clip(m0_ar_pred, vas_min, vas_max) - ar_y[:, None])
    m4_errors = np.abs(np.clip(m4_pred, vas_min, vas_max) - ar_y[:, None])
    comparisons: dict[str, dict[str, Any]] = {}
    for name, a, b, groups, evaluation_mask, target, indices, enhanced, baseline in (
        (
            "M3_vs_M0-static",
            m3_errors,
            static_errors,
            subjects,
            mask,
            y,
            [(int(row), int(window)) for row in range(n) for window in range(n_windows)],
            m3,
            m0,
        ),
        (
            "M4_vs_M0-AR",
            m4_errors,
            ar_errors,
            ar_groups,
            ar_mask[:, None],
            ar_y[:, None],
            [(int(row), int(window)) for row, window in ar_window_index],
            m4,
            m0_ar,
        ),
    ):
        comparisons[name] = {
            "permutation": _permutation_delta(
                a, b, groups, evaluation_mask, n_permutations=n_permutations, rng=rng
            ),
            "cluster_bootstrap": _cluster_bootstrap(
                a, b, groups, evaluation_mask, n_bootstrap=n_bootstrap, rng=rng
            ),
            "fairness_audit": {
                "same_target": True,
                "same_evaluation_mask": True,
                "same_subject_folds": enhanced["fold_hash"] == baseline["fold_hash"],
                "target_sha256": _array_hash(np.asarray(target, dtype=float)),
                "evaluation_mask_sha256": _array_hash(np.asarray(evaluation_mask, dtype=bool)),
                "evaluation_index_sha256": hashlib.sha256(_canonical_json(indices).encode("utf-8")).hexdigest(),
                "enhanced_fold_sha256": enhanced["fold_hash"],
                "baseline_fold_sha256": baseline["fold_hash"],
            },
        }
        threshold_frozen = minimum_gain_mae is not None and gain_alpha is not None
        comparisons[name]["threshold_status"] = "frozen" if threshold_frozen else "unfrozen"
        comparisons[name]["conclusion"] = "gain_not_demonstrated"
        if (
            minimum_gain_mae is not None
            and gain_alpha is not None
            and comparisons[name]["permutation"]["observed_delta_mae"] <= -float(minimum_gain_mae)
            and comparisons[name]["permutation"]["p_value"] < float(gain_alpha)
        ):
            comparisons[name]["conclusion"] = "gain_supported"
    try:
        software_version = metadata.version("fnirs-flow")
    except metadata.PackageNotFoundError:
        from fnirs_flow import __version__ as software_version
    try:
        scipy_version = metadata.version("scipy")
    except metadata.PackageNotFoundError:
        scipy_version = "not-installed"
    result = {
        "model_ids": list(MODEL_IDS),
        "metrics": metrics,
        "oof_predictions": prediction_rows,
        "comparisons": comparisons,
        "m4_recursive_sensitivity": {
            "prediction_raw": recursive_prediction,
            "prediction_clipped": np.clip(recursive_prediction, vas_min, vas_max),
            "chain_active": recursive_chain_active,
            "restart_policy": "never_restart_after_interruption",
        },
        "folds": {
            key: value.get("folds", [])
            for key, value in {"M0-static": m0, "M3": m3, "M0-AR": m0_ar, "M4": m4}.items()
        },
        "duplicate_audit": duplicate_audit,
        "resampling_standard_met": standard_met,
        "information_boundary": {
            "m3": "static plus same-window physiology only",
            "m4": "history through t only; target-window signal/QC excluded",
            "evaluation_mask_sources": sorted(mask_sources),
        },
        "provenance": {
            "software_version": software_version,
            "python": sys.version,
            "platform": platform.platform(),
            "dependency_versions": {"numpy": np.__version__, "scipy": scipy_version},
            "git_commit": str(git_commit).lower(),
            "execution_command": execution_command,
            "input_sha256": str(input_sha256).lower(),
            "random_seed": random_seed,
        },
        "config_hash": hashlib.sha256(
            json.dumps(
                {
                    "windows": windows,
                    "vas_range": [vas_min, vas_max],
                    "inner_folds": inner_folds,
                    "n_permutations": n_permutations,
                    "n_bootstrap": n_bootstrap,
                    "random_seed": random_seed,
                    "modality_pca_variance": modality_pca_variance,
                    "feature_selection_k": feature_selection_k,
                    "minimum_gain_mae": minimum_gain_mae,
                    "gain_alpha": gain_alpha,
                    "evaluation_mask_schema": evaluation_mask_schema,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest(),
    }
    if outdir is not None:
        result["artifacts"] = write_continuous_vas_derivatives(outdir, result)
    return result
