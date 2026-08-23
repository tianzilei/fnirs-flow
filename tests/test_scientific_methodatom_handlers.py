"""Contract tests for the executable declarative MethodAtom handlers."""

from __future__ import annotations

import numpy as np
import pytest

from fnirs_flow.execution.operations import OperationContext, create_default_registry
from fnirs_flow.registry.atom_templates import ALL_METHOD_ATOM_TEMPLATES


class Adapter:
    backend_id = "mne_nirs"


def run(operation: str, raw, **parameters):
    return create_default_registry().execute(
        operation,
        OperationContext(adapter=Adapter(), raw=raw, parameters=parameters),
    )


def test_every_methodatom_has_a_registered_handler():
    registry = create_default_registry()
    missing = []
    for template in ALL_METHOD_ATOM_TEMPLATES:
        operation = str(template.operation or template.atom_type)
        backend = template.backend_binding.backend_id if template.backend_binding else "mne_nirs"
        spec = registry.get(operation)
        if spec is None or spec.handler_factory_for(backend) is None:
            missing.append((template.template_id, operation, backend))
    # Advanced Cedalion/DOT atoms intentionally remain unverified until
    # representative segmentation/mesh inputs are available. Their adapter
    # method binding is checked separately by the Cedalion contract suite.
    assert all(backend == "cedalion" for _, _, backend in missing)


@pytest.mark.parametrize(
    ("operation", "raw", "parameters"),
    [
        ("descriptive_statistics", [1, 2, 3], {}),
        ("one_sample_ttest", [1, 2, 3, 4], {"popmean": 0}),
        ("independent_ttest", [1, 2, 4, 5], {"groups": [0, 0, 1, 1]}),
        ("normality_test", np.arange(20), {}),
        ("bonferroni_correction", [0.01, 0.04], {}),
        ("cohens_d", [1, 2, 3], {"groups": [[1, 2, 3], [0, 1, 2]]}),
        ("feature_extraction", np.arange(20).reshape(2, 10), {}),
        ("resting_connectivity", np.arange(20).reshape(2, 10), {}),
        ("graph_theory_metrics", np.eye(3), {"threshold": 0.5}),
        ("laterality_index", np.array([[2.0], [1.0]]), {}),
        ("dpf_calculation", 30, {"age": 30}),
        ("dcm_fnirs", np.arange(40).reshape(2, 20), {}),
    ],
)
def test_scientific_handlers_return_results(operation, raw, parameters):
    result = run(operation, raw, **parameters)
    assert result is not None


def test_traditional_machine_learning_handler_trains():
    rng = np.random.default_rng(7)
    X = np.r_[rng.normal(-1, 0.1, (10, 4)), rng.normal(1, 0.1, (10, 4))]
    y = np.r_[np.zeros(10, dtype=int), np.ones(10, dtype=int)]
    result = run("svm", X, y=y)
    assert result["mean_score"] > 0.9


def test_deep_learning_handler_requires_declared_extra_when_torch_missing():
    try:
        import torch  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError, match="deep-learning"):
            run("1d_cnn_classification", np.ones((4, 2, 16)), y=[0, 0, 1, 1])


def test_all_deep_learning_handlers_train_when_torch_is_available():
    pytest.importorskip("torch")
    from fnirs_flow.execution.deep_learning_handlers import DEEP_LEARNING_OPERATIONS

    rng = np.random.default_rng(4)
    X = rng.normal(size=(8, 2, 16)).astype("float32")
    y = np.array([0, 1, 0, 1, 0, 1, 0, 1])
    for operation in DEEP_LEARNING_OPERATIONS:
        result = run(operation, X, y=y, epochs=1, hidden_size=4, n_heads=1)
        assert result is not None
        if operation != "vae_representation":
            assert "predictions" in result


def test_proprietary_reader_fails_with_actionable_conversion_path():
    with pytest.raises(NotImplementedError, match="convert.*SNIRF"):
        run("iss_reader", None, path="recording.iss")


@pytest.mark.parametrize(
    ("operation", "raw", "parameters"),
    [
        ("cross_correlation", np.vstack([np.arange(32), np.arange(32)]), {}),
        ("mbll_conversion", np.ones((2, 32)), {"pathlength_cm": 3.0}),
        ("precoloring", np.arange(64).reshape(2, 32), {"sigma": 1.0}),
        ("tfce_enhancement", np.array([[0.0, 1.0, 2.0]]), {"step": 0.1}),
        ("combat_harmonization", np.arange(24).reshape(2, 12), {"batch": [0] * 6 + [1] * 6}),
        ("nuisance_glm", np.arange(12), {"X": np.column_stack([np.ones(12), np.arange(12)])}),
        ("logistic_regression", [0, 1, 0, 1, 0, 1], {"X": [[-3], [-2], [-1], [1], [2], [3]]}),
    ],
)
def test_new_scientific_families_execute(operation, raw, parameters):
    result = run(operation, raw, **parameters)
    assert result is not None


def test_combat_rejects_misaligned_batch_labels():
    with pytest.raises(ValueError, match="one batch/site label per observation"):
        run("combat_harmonization", np.ones((2, 10)), batch=[0, 1])


def test_scientific_allowlist_contains_no_unimplemented_dispatch_branch():
    smoke_inputs = {
        "cross_correlation": (np.ones((2, 20)), {}),
        "mbll_conversion": (np.ones((2, 20)), {}),
        "precoloring": (np.ones((2, 20)), {}),
        "tfce_enhancement": (np.ones((2, 20)), {}),
    }
    for operation, (raw, parameters) in smoke_inputs.items():
        try:
            run(operation, raw, **parameters)
        except NotImplementedError as exc:  # pragma: no cover - regression guard
            pytest.fail(f"{operation} was registered without implementation: {exc}")
