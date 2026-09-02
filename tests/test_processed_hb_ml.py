import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from fnirs_flow.processed_hb import run_continuous_vas_models, write_continuous_vas_derivatives
from fnirs_flow.processed_hb.ml import nested_grouped_regression, validate_information_boundary


def test_nested_grouped_regression_has_disjoint_subject_folds():
    rng = np.random.default_rng(1)
    groups = np.repeat(["s1", "s2", "s3"], 4)
    X = rng.normal(size=(12, 3))
    y = X[:, 0] * 2 + rng.normal(size=12) * 0.01
    result = nested_grouped_regression(X, y, groups, inner_folds=2)
    assert np.isfinite(result["predictions"]).all()
    for fold in result["folds"]:
        assert not set(fold["outer_test_groups"]) & set(fold["outer_train_groups"])


def test_nested_grouped_regression_random_state_controls_inner_folds():
    rng = np.random.default_rng(17)
    groups = np.repeat([f"s{i}" for i in range(8)], 3)
    X = rng.normal(size=(24, 3))
    y = X[:, 0] + rng.normal(size=24) * 0.01

    first = nested_grouped_regression(X, y, groups, inner_folds=3, random_state=4)
    repeated = nested_grouped_regression(X, y, groups, inner_folds=3, random_state=4)
    different = nested_grouped_regression(X, y, groups, inner_folds=3, random_state=9)

    first_inner = first["folds"][0]["inner_folds"]
    assert first_inner == repeated["folds"][0]["inner_folds"]
    assert first_inner != different["folds"][0]["inner_folds"]


def test_information_boundary_rejects_future_columns():
    with pytest.raises(ValueError):
        validate_information_boundary(["hbo_t7", "vas_t8"], future_columns=["vas_t8"])


def test_inner_folds_and_transforms_are_subject_disjoint_and_fold_local():
    rng = np.random.default_rng(4)
    groups = np.repeat([f"s{i}" for i in range(5)], 3)
    X = rng.normal(size=(15, 2))
    y = X[:, 0]
    observations = []
    result = nested_grouped_regression(
        X,
        y,
        groups,
        inner_folds=3,
        transform_observer=lambda scope, train, test: observations.append((scope, train, test)),
    )
    assert observations
    for fold in result["folds"]:
        assert fold["outer_train_group_hash"] and fold["outer_test_group_hash"]
        for inner in fold["inner_folds"]:
            assert not set(inner["train_groups"]) & set(inner["validation_groups"])
            assert inner["train_group_hash"] and inner["validation_group_hash"]
    assert all(not set(groups[train]) & set(groups[test]) for _, train, test in observations)


@pytest.mark.parametrize(
    "schema",
    [
        [{"name": "vas_t7", "kind": "target"}],
        [{"name": "future_signal_t8", "kind": "signal", "relative_step": 1}],
        [{"name": "future_qc_t8", "kind": "qc", "relative_step": 1}],
        [{"name": "canary_future", "kind": "feature"}],
        [{"name": "subject_id", "kind": "id"}],
        [{"name": "capture_date", "kind": "date"}],
    ],
)
def test_information_boundary_rejects_leakage_schema(schema):
    with pytest.raises(ValueError, match="information boundary violation"):
        validate_information_boundary(schema, task="m4", prediction_time=1.0)


def _vas_fixture(seed=2):
    rng = np.random.default_rng(seed)
    subjects = np.array([f"s{i}" for i in range(6)])
    static = rng.normal(size=(6, 2))
    physiology = rng.normal(size=(6, 5, 2))
    vas = 5 + static[:, :1] + 0.2 * physiology[:, :, 0]
    mask = np.ones_like(vas, dtype=bool)
    return subjects, static, physiology, vas, mask


def test_project_vas_runner_outputs_all_models_fair_masks_and_oof():
    subjects, static, physiology, vas, mask = _vas_fixture()
    result = run_continuous_vas_models(
        subject_ids=subjects,
        window_ids=["t7", "t8", "t9", "t10", "t11"],
        vas=vas,
        target_mask=mask,
        static_features=static,
        physiology_features=physiology,
        static_feature_schema=[{"name": "age"}, {"name": "baseline"}],
        physiology_feature_schema=[{"name": "hbo_same_window"}, {"name": "ecg_same_window"}],
        inner_folds=3,
        n_permutations=31,
        n_bootstrap=31,
        random_seed=7,
        evaluation_mask_schema={"sources": ["frozen_population", "frozen_target_availability"]},
        allow_reduced_resampling_for_testing=True,
    )
    assert result["model_ids"] == ["M0-static", "M3", "M0-AR", "M4", "naive_persistence"]
    assert len(result["oof_predictions"]) == 6 * 5 * 2 + 6 * 4 * 3
    assert all(row["evaluation_mask"] for row in result["oof_predictions"])
    assert result["comparisons"]["M3_vs_M0-static"]["permutation"]["n"] == 31
    assert result["comparisons"]["M4_vs_M0-AR"]["cluster_bootstrap"]["n"] == 31
    assert result["comparisons"]["M3_vs_M0-static"]["threshold_status"] == "unfrozen"
    assert result["comparisons"]["M3_vs_M0-static"]["conclusion"] == "gain_not_demonstrated"
    for comparison in result["comparisons"].values():
        audit = comparison["fairness_audit"]
        assert audit["same_target"] is True
        assert audit["same_evaluation_mask"] is True
        assert audit["same_subject_folds"] is True
        assert audit["target_sha256"] and audit["evaluation_mask_sha256"] and audit["evaluation_index_sha256"]
    for model in ("M0-static", "M3", "M0-AR", "M4"):
        for fold in result["folds"][model]:
            assert not set(fold["outer_train_groups"]) & set(fold["outer_test_groups"])


def test_recursive_m4_never_restarts_after_missing_history():
    subjects, static, physiology, vas, mask = _vas_fixture()
    mask[0, 2] = False
    result = run_continuous_vas_models(
        subject_ids=subjects,
        window_ids=["t7", "t8", "t9", "t10", "t11"],
        vas=vas,
        target_mask=mask,
        static_features=static,
        physiology_features=physiology,
        static_feature_schema=["age", "baseline"],
        physiology_feature_schema=["hbo_same_window", "ecg_same_window"],
        inner_folds=3,
        n_permutations=3,
        n_bootstrap=3,
        evaluation_mask_schema={"sources": ["frozen_population", "frozen_target_availability"]},
        allow_reduced_resampling_for_testing=True,
    )
    active = result["m4_recursive_sensitivity"]["chain_active"]
    assert active[0].tolist() == [False, True, True, False, False]
    assert result["m4_recursive_sensitivity"]["restart_policy"] == "never_restart_after_interruption"


def test_subject_equal_mae_differs_from_row_weighted_mae_when_counts_differ():
    X = np.arange(12, dtype=float)[:, None]
    y = np.concatenate([np.zeros(10), [100.0], [0.0]])
    groups = np.array(["many"] * 10 + ["large", "small"])
    result = nested_grouped_regression(X, y, groups, inner_folds=2)
    assert result["subject_weighted_mae"] != pytest.approx(result["mae"])


def test_label_shuffle_destroys_predictive_signal():
    rng = np.random.default_rng(12)
    groups = np.repeat([f"s{i}" for i in range(12)], 4)
    X = rng.normal(size=(48, 3))
    y = 5 * X[:, 0] + rng.normal(scale=0.05, size=48)
    signal = nested_grouped_regression(X, y, groups, inner_folds=5)["subject_weighted_mae"]
    shuffled = nested_grouped_regression(X, rng.permutation(y), groups, inner_folds=5)["subject_weighted_mae"]
    assert shuffled > signal * 3


def test_modality_pca_and_feature_selection_are_fit_inside_each_fold():
    rng = np.random.default_rng(22)
    groups = np.repeat([f"s{i}" for i in range(6)], 3)
    X = rng.normal(size=(18, 6))
    y = X[:, 0] - X[:, 3]
    result = nested_grouped_regression(
        X,
        y,
        groups,
        inner_folds=3,
        modality_groups=["fnirs"] * 3 + ["ecg_egg"] * 3,
        pca_components={"fnirs": 2, "ecg_egg": 2},
        feature_selection_k=3,
    )
    for fold in result["folds"]:
        transform = fold["transform"]
        assert {block["modality"] for block in transform["modality_blocks"]} == {"fnirs", "ecg_egg"}
        assert len(transform["feature_selection"]["selected_indices"]) == 3
        assert all(len(block["components"][0]) == 2 for block in transform["modality_blocks"])


def test_project_runner_rejects_target_window_qc_evaluation_mask():
    subjects, static, physiology, vas, mask = _vas_fixture()
    with pytest.raises(ValueError, match="EVALUATION_MASK_INFORMATION_BOUNDARY_INVALID"):
        run_continuous_vas_models(
            subject_ids=subjects,
            record_ids=[f"record-{index}" for index in range(len(subjects))],
            window_ids=["t7", "t8", "t9", "t10", "t11"],
            vas=vas,
            target_mask=mask,
            static_features=static,
            physiology_features=physiology,
            static_feature_schema=["age", "baseline"],
            physiology_feature_schema=["hbo_same_window", "ecg_same_window"],
            inner_folds=3,
            n_permutations=3,
            n_bootstrap=3,
            evaluation_mask_schema={"sources": ["target_qc"]},
            allow_reduced_resampling_for_testing=True,
        )


def test_project_derivative_writer_rejects_reduced_resampling(tmp_path):
    subjects, static, physiology, vas, mask = _vas_fixture()
    with pytest.raises(ValueError, match="REDUCED_RESAMPLING_CANNOT_WRITE_PROJECT_DERIVATIVES"):
        run_continuous_vas_models(
            subject_ids=subjects,
            record_ids=[f"record-{index}" for index in range(len(subjects))],
            window_ids=["t7", "t8", "t9", "t10", "t11"],
            vas=vas,
            target_mask=mask,
            static_features=static,
            physiology_features=physiology,
            static_feature_schema=["age", "baseline"],
            physiology_feature_schema=["hbo_same_window", "ecg_same_window"],
            inner_folds=3,
            n_permutations=3,
            n_bootstrap=3,
            evaluation_mask_schema={"sources": ["frozen_population"]},
            allow_reduced_resampling_for_testing=True,
            outdir=tmp_path,
        )


def test_direct_derivative_writer_cannot_bypass_resampling_gate(tmp_path):
    subjects, static, physiology, vas, mask = _vas_fixture()
    result = run_continuous_vas_models(
        subject_ids=subjects,
        window_ids=["t7", "t8", "t9", "t10", "t11"],
        vas=vas,
        target_mask=mask,
        static_features=static,
        physiology_features=physiology,
        static_feature_schema=["age", "baseline"],
        physiology_feature_schema=["hbo_same_window", "ecg_same_window"],
        inner_folds=3,
        n_permutations=3,
        n_bootstrap=3,
        evaluation_mask_schema={"sources": ["frozen_population"]},
        allow_reduced_resampling_for_testing=True,
    )
    with pytest.raises(ValueError, match="FORMAL_DERIVATIVE_RESAMPLING_STANDARD_NOT_MET"):
        write_continuous_vas_derivatives(tmp_path, result)


def test_formal_derivative_writer_records_recomputable_hashes_and_provenance(tmp_path):
    result = {
        "model_ids": ["M0-static", "M3", "M0-AR", "M4", "naive_persistence"],
        "oof_predictions": [
            {
                "model_id": "M3",
                "subject_id": "s1",
                "record_id": "r1",
                "window_id": "t7",
                "target": 5.0,
                "evaluation_mask": True,
                "prediction_raw": 5.1,
                "prediction_clipped": 5.1,
                "range_corrected": False,
            }
        ],
        "metrics": {"M3": {"subject_equal_mae": 0.1}},
        "comparisons": {
            "M3_vs_M0-static": {
                "permutation": {"n": 10_000},
                "cluster_bootstrap": {"n": 2_000},
            }
        },
        "folds": {},
        "m4_recursive_sensitivity": {"prediction_raw": np.array([[1.0]])},
        "duplicate_audit": {"cross_subject_duplicate_count": 0},
        "resampling_standard_met": True,
        "information_boundary": {"m3": "same-window"},
        "config_hash": "a" * 64,
        "provenance": {
            "software_version": "1.3.0",
            "python": "3.11",
            "dependency_versions": {"numpy": np.__version__},
            "git_commit": "b" * 40,
            "execution_command": "fnirs-flow run-continuous-vas --input frozen.json --outdir <output>",
            "input_sha256": "c" * 64,
        },
    }
    paths = write_continuous_vas_derivatives(tmp_path, result)
    manifest = json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))
    assert manifest["provenance"]["input_sha256"] == "c" * 64
    for relative, expected in manifest["artifact_sha256"].items():
        assert hashlib.sha256((tmp_path / relative).read_bytes()).hexdigest() == expected


def test_oof_predictions_are_generated_only_for_held_out_subjects():
    rng = np.random.default_rng(30)
    groups = np.repeat([f"s{i}" for i in range(5)], 2)
    X = rng.normal(size=(10, 2))
    y = X[:, 0]
    seen = []
    result = nested_grouped_regression(
        X,
        y,
        groups,
        inner_folds=3,
        transform_observer=lambda scope, train, test: seen.append((scope, set(groups[train]), set(groups[test]))),
    )
    outer = [entry for entry in seen if entry[0] == "outer"]
    assert len(outer) == len(set(groups))
    assert all(not train & test and len(test) == 1 for _, train, test in outer)
    assert np.isfinite(result["predictions"]).all()
