from __future__ import annotations

import csv
from dataclasses import replace

import numpy as np
import pytest

from fnirs_flow.analysis.design_models import bind_design_contrasts, compile_post_event_fir
from fnirs_flow.data.frozen_events import FrozenEvent, ingest_frozen_events
from fnirs_flow.execution.processed_hb_pipeline import _contrast_definitions


def _events():
    return [FrozenEvent("F1", 5.0, 5.0, "condition_a", "w1", "1")]


def test_design_hash_is_stable_and_sensitive_to_events_time_parameters_and_contrasts():
    time = np.arange(0, 60, 0.5)
    first = compile_post_event_fir(time, _events())
    same = compile_post_event_fir(time.copy(), _events())
    changed_event = compile_post_event_fir(time, [replace(_events()[0], onset=6.0)])
    changed_time = compile_post_event_fir(time + 0.01, _events())
    changed_parameter = compile_post_event_fir(time, _events(), bins=((0, 5), (5, 10), (10, 15)))
    assert first.design_hash == same.design_hash
    hashes = {first.design_hash, changed_event.design_hash, changed_time.design_hash, changed_parameter.design_hash}
    assert len(hashes) == 4
    definition = [{"contrast_id": "joint", "component_names": ["a"], "weights": [1, 0, 0, 0]}]
    bound = bind_design_contrasts(first, definition, contrast_input_sha256="a" * 64)
    rebound = bind_design_contrasts(first, definition, contrast_input_sha256="b" * 64)
    assert first.design_hash != bound.design_hash != rebound.design_hash


def test_multicomponent_contrast_binds_columns_and_checks_duplicates(tmp_path):
    bundle = compile_post_event_fir(np.arange(0, 60, 0.5), _events())
    path = tmp_path / "contrast.csv"
    fields = ["model_id", "contrast_id", "component_id", "regressor", "weight"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            [
                {
                    "model_id": bundle.model_id,
                    "contrast_id": "joint",
                    "component_id": "early",
                    "regressor": "offset__0_10s",
                    "weight": 1,
                },
                {
                    "model_id": bundle.model_id,
                    "contrast_id": "joint",
                    "component_id": "late",
                    "regressor": "offset__20_30s",
                    "weight": 1,
                },
            ]
        )
    definitions = _contrast_definitions(path, [bundle])[bundle.model_id]
    assert definitions[0]["component_names"] == ["early", "late"]
    assert np.asarray(definitions[0]["weights"]).shape == (2, 4)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"{bundle.model_id},joint,early,offset__0_10s,1\n")
    with pytest.raises(ValueError, match="duplicate contrast weight"):
        _contrast_definitions(path, [bundle])


def test_authoritative_contrast_table_rejects_unknown_or_missing_models(tmp_path):
    bundle = compile_post_event_fir(np.arange(0, 60, 0.5), _events())
    path = tmp_path / "contrast.csv"
    path.write_text(
        "model_id,contrast_id,regressor,weight\nunknown,c,offset__0_10s,1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown models"):
        _contrast_definitions(path, [bundle])
    path.write_text(
        "model_id,contrast_id,regressor,weight\nglm_conditions_canonical_td_v1,c,offset__0_10s,1\n",
        encoding="utf-8",
    )
    other = replace(bundle, model_id="glm_conditions_canonical_td_v1")
    with pytest.raises(ValueError, match="missing model definitions"):
        _contrast_definitions(path, [bundle, other])


def test_frozen_events_reject_nonfinite_timing_and_apply_coverage_tolerance(tmp_path):
    path = tmp_path / "events.tsv"
    path.write_text(
        "fnirs_record_id\tonset\tduration\ttrial_type\twindow_id\tsync_uncertainty_s\n"
        "F1\tnan\t1\tcondition_a\tw1\t0.1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-finite event timing"):
        ingest_frozen_events(path, "F1")
    path.write_text(
        "fnirs_record_id\tonset\tduration\ttrial_type\twindow_id\n"
        "F1\t9.9\t0.15\tM1\tw1\n",
        encoding="utf-8",
    )
    excluded = ingest_frozen_events(path, "F1", coverage=(0, 10), coverage_tolerance_s=0.0)
    included = ingest_frozen_events(path, "F1", coverage=(0, 10), coverage_tolerance_s=0.1)
    assert excluded.audit[0]["reason_code"] == "EVENT_OUTSIDE_COVERAGE"
    assert included.events[0].event_eligible is True
