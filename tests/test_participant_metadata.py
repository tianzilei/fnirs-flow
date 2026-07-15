from __future__ import annotations

import csv
import json

from fnirs_flow.data.manifest import DataManifest, SubjectSessionRun
from fnirs_flow.data.participants import (
    build_group_design_matrix,
    compile_contrast_expression,
    compile_group_contrasts,
    fit_group_glm,
    join_participant_metadata,
    project_combat_manifest,
    project_dpf_inputs,
    project_label_vector,
    project_outcome_vector,
    project_site_metadata,
    read_participant_table,
    summarize_cluster_inference,
    validate_participant_table,
    validate_site_group_confound,
    validate_subject_split_no_leakage,
    write_participant_table_artifacts,
)


def _write_participants(path):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["participant_id", "include", "group", "age", "site"])
        writer.writerow(["sub-01", "1", "control", "24", "site_A"])
        writer.writerow(["sub-02", "1", "patient", "31", "site_B"])
        writer.writerow(["sub-03", "0", "patient", "35", "site_B"])


def test_participant_table_read_validate_and_artifacts(tmp_path):
    table_path = tmp_path / "participants.tsv"
    _write_participants(table_path)
    manifest = DataManifest(
        subject_session_runs=[
            SubjectSessionRun(subject="01", path="a.snirf"),
            SubjectSessionRun(subject="02", path="b.snirf"),
            SubjectSessionRun(subject="04", path="c.snirf"),
        ]
    )

    table = read_participant_table(table_path)
    report = validate_participant_table(table, manifest)
    bundle = write_participant_table_artifacts(table, tmp_path / "compiled", manifest=manifest)

    assert table.source.sha256
    assert report.join_preview.matched_subjects == ["sub-01", "sub-02"]
    assert report.join_preview.unmatched_results == ["sub-04"]
    assert report.join_preview.excluded_subjects == ["sub-03"]
    assert bundle.validation_report.warnings
    assert (tmp_path / "compiled" / "participant_join_audit.csv").exists()


def test_join_and_projection_helpers(tmp_path):
    table_path = tmp_path / "participants.tsv"
    _write_participants(table_path)
    table = read_participant_table(table_path)

    joined = join_participant_metadata([{"subject": "01", "beta": 1.0}, {"subject": "03", "beta": 9.0}], table)
    labels = project_label_vector(table)
    sites = project_site_metadata(table)

    assert joined["matched_subjects"] == ["sub-01", "sub-03"]
    assert joined["excluded_subjects"] == ["sub-03"]
    assert labels["labels"] == [
        {"participant_id": "sub-01", "label": "control"},
        {"participant_id": "sub-02", "label": "patient"},
    ]
    assert sites["rows"][1]["site"] == "site_B"


def test_dpf_outcome_and_combat_projection_helpers(tmp_path):
    table_path = tmp_path / "participants.tsv"
    table_path.write_text(
        (
            "participant_id\tinclude\tgroup\tage\tsite\tclinical_score\n"
            "sub-01\t1\tcontrol\t24\tsite_A\t8.5\n"
            "sub-02\t1\tpatient\t31\tsite_B\t18.0\n"
            "sub-03\t0\tpatient\t35\tsite_B\t20.0\n"
        ),
        encoding="utf-8",
    )
    table = read_participant_table(table_path)

    dpf = project_dpf_inputs(table)
    outcome = project_outcome_vector(table, "clinical_score", outcome_kind="clinical")
    combat = project_combat_manifest(table, biological_covariates=["age", "group"])

    assert dpf["type"] == "DPFInput"
    assert dpf["rows"] == [
        {"participant_id": "sub-01", "age_years": 24.0},
        {"participant_id": "sub-02", "age_years": 31.0},
    ]
    assert outcome["rows"][1]["value"] == 18.0
    assert combat["subject_session_runs"][0]["site"] == "site_A"
    assert combat["biological_covariates"] == ["age", "group"]


def test_group_design_matrix_two_sample():
    rows = [
        {"participant_id": "sub-01", "group": "control", "beta": 1.0, "roi": "motor"},
        {"participant_id": "sub-02", "group": "patient", "beta": 2.0, "roi": "motor"},
        {"participant_id": "sub-03", "group": "control", "beta": 1.5, "roi": "motor"},
        {"participant_id": "sub-04", "group": "patient", "beta": 2.5, "roi": "motor"},
    ]
    design = build_group_design_matrix(
        rows,
        design_type="two_sample_t",
    )

    assert design.column_names == ["group[control]", "group[patient]"]
    assert design.rank == 2
    assert design.design_matrix[:2] == [
        {"group[control]": 1.0, "group[patient]": 0.0},
        {"group[control]": 0.0, "group[patient]": 1.0},
    ]
    glm = fit_group_glm(design)
    assert glm.contrasts
    assert glm.corrected[0]["correction_method"] == "fdr_bh"


def test_group_design_matrix_paired_t_and_named_contrasts():
    rows = [
        {"participant_id": "sub-01", "condition": "pre", "beta": 1.0, "roi": "motor"},
        {"participant_id": "sub-01", "condition": "post", "beta": 2.0, "roi": "motor"},
        {"participant_id": "sub-02", "condition": "pre", "beta": 1.5, "roi": "motor"},
        {"participant_id": "sub-02", "condition": "post", "beta": 2.5, "roi": "motor"},
        {"participant_id": "sub-03", "condition": "pre", "beta": 2.0, "roi": "motor"},
        {"participant_id": "sub-03", "condition": "post", "beta": 4.0, "roi": "motor"},
    ]
    design = build_group_design_matrix(rows, design_type="paired_t", condition_column="condition")
    assert design.column_names == ["intercept"]
    assert [row["beta"] for row in design.analysis_table] == [1.0, 1.0, 2.0]

    glm = fit_group_glm(
        design,
        contrasts=compile_group_contrasts(
            [{"name": "post > pre", "type": "T", "expression": "intercept"}],
            design.column_names,
        ),
    )
    assert glm.contrasts[0]["contrast_name"] == "post > pre"
    assert glm.contrasts[0]["contrast_type"] == "T"


def test_compile_t_and_f_contrasts():
    columns = ["group[control]", "group[patient]", "age_centered"]
    assert compile_contrast_expression("group[patient] - group[control]", columns) == [-1.0, 1.0, 0.0]
    compiled = compile_group_contrasts(
        [
            {"name": "Patient > Control", "type": "T", "expression": "group[patient] - group[control]"},
            {"name": "Group omnibus", "type": "F", "terms": ["group"]},
        ],
        columns,
    )
    assert compiled[0].weights == [-1.0, 1.0, 0.0]
    assert compiled[1].contrast_type == "F"
    assert compiled[1].weight_matrix == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


def test_fit_group_glm_f_contrast():
    rows = [
        {"participant_id": "sub-01", "group": "control", "beta": 1.0, "roi": "motor"},
        {"participant_id": "sub-02", "group": "control", "beta": 1.2, "roi": "motor"},
        {"participant_id": "sub-03", "group": "control", "beta": 0.8, "roi": "motor"},
        {"participant_id": "sub-04", "group": "patient", "beta": 2.0, "roi": "motor"},
        {"participant_id": "sub-05", "group": "patient", "beta": 2.2, "roi": "motor"},
        {"participant_id": "sub-06", "group": "patient", "beta": 1.8, "roi": "motor"},
    ]
    design = build_group_design_matrix(rows, design_type="two_sample_t")
    glm = fit_group_glm(
        design,
        contrasts=compile_group_contrasts(
            [{"name": "Group omnibus", "type": "F", "terms": ["group"]}],
            design.column_names,
        ),
    )
    assert glm.contrasts[0]["contrast_type"] == "F"
    assert float(glm.contrasts[0]["f_value"]) > 0
    assert glm.effect_sizes[0]["effect_size_metric"] == "partial_eta_squared"


def test_group_metadata_risk_validators():
    confounded_rows = [
        {"participant_id": "sub-01", "group": "control", "site": "site_A"},
        {"participant_id": "sub-02", "group": "patient", "site": "site_B"},
    ]
    balanced_rows = [
        {"participant_id": "sub-01", "group": "control", "site": "site_A"},
        {"participant_id": "sub-02", "group": "patient", "site": "site_A"},
        {"participant_id": "sub-03", "group": "control", "site": "site_B"},
        {"participant_id": "sub-04", "group": "patient", "site": "site_B"},
    ]
    assert validate_site_group_confound(confounded_rows) is True
    assert validate_site_group_confound(balanced_rows) is False

    validate_subject_split_no_leakage(["sub-01"], ["sub-02"])
    try:
        validate_subject_split_no_leakage(["sub-01", "sub-02"], ["sub-02"])
    except ValueError as exc:
        assert "ML_SUBJECT_LEAKAGE" in str(exc)
    else:
        raise AssertionError("Expected leakage validation to fail")


def test_full_factorial_design_matrix_includes_interactions():
    rows = [
        {"participant_id": "sub-01", "group": "control", "sex": "F", "beta": 1.0},
        {"participant_id": "sub-02", "group": "control", "sex": "M", "beta": 1.2},
        {"participant_id": "sub-03", "group": "patient", "sex": "F", "beta": 2.0},
        {"participant_id": "sub-04", "group": "patient", "sex": "M", "beta": 2.2},
    ]
    design = build_group_design_matrix(rows, design_type="full_factorial", factors=["group", "sex"])

    assert "intercept" in design.column_names
    assert "group[patient]" in design.column_names
    assert "sex[M]" in design.column_names
    assert "group[patient]:sex[M]" in design.column_names
    assert design.rank == 4


def test_repeated_mixed_design_adds_subject_proxy_columns():
    rows = [
        {"participant_id": "sub-01", "group": "control", "timepoint": "pre", "beta": 1.0},
        {"participant_id": "sub-01", "group": "control", "timepoint": "post", "beta": 1.5},
        {"participant_id": "sub-02", "group": "patient", "timepoint": "pre", "beta": 2.0},
        {"participant_id": "sub-02", "group": "patient", "timepoint": "post", "beta": 2.5},
        {"participant_id": "sub-03", "group": "control", "timepoint": "pre", "beta": 1.1},
        {"participant_id": "sub-03", "group": "control", "timepoint": "post", "beta": 1.4},
        {"participant_id": "sub-04", "group": "patient", "timepoint": "pre", "beta": 2.2},
        {"participant_id": "sub-04", "group": "patient", "timepoint": "post", "beta": 2.7},
    ]
    design = build_group_design_matrix(
        rows,
        design_type="mixed_effects",
        factors=["group"],
        within_subject_factors=["timepoint"],
        random_effects=["participant_id"],
    )

    assert "intercept" in design.column_names
    assert "timepoint[post]" in design.column_names
    assert any(column.startswith("participant_id[") for column in design.column_names)
    assert design.rank == len(design.column_names)


def test_fit_group_glm_robust_permutation_and_sensitivity():
    rows = [
        {"participant_id": "sub-01", "group": "control", "site": "A", "beta": 1.0, "roi": "motor"},
        {"participant_id": "sub-02", "group": "control", "site": "A", "beta": 1.1, "roi": "motor"},
        {"participant_id": "sub-03", "group": "control", "site": "B", "beta": 0.9, "roi": "motor"},
        {"participant_id": "sub-04", "group": "patient", "site": "B", "beta": 2.0, "roi": "motor"},
        {"participant_id": "sub-05", "group": "patient", "site": "A", "beta": 2.1, "roi": "motor"},
        {"participant_id": "sub-06", "group": "patient", "site": "B", "beta": 1.9, "roi": "motor"},
    ]
    design = build_group_design_matrix(rows, design_type="two_sample_t")
    glm = fit_group_glm(
        design,
        contrasts=compile_group_contrasts(
            [{"name": "Patient > Control", "type": "T", "expression": "group[patient] - group[control]"}],
            design.column_names,
        ),
        covariance="hc0",
        permutation_count=9,
        random_seed=7,
        sensitivity_branches=[{"name": "site A only", "filter": {"site": "A"}}],
    )

    assert glm.contrasts[0]["covariance"] == "hc0"
    assert 0.0 < float(glm.contrasts[0]["permutation_p_value"]) <= 1.0
    assert glm.corrected[0]["permutation_count"] == 9
    assert glm.sensitivity and glm.sensitivity[0]["branch_name"] == "site A only"


def test_cluster_inference_summary_groups_adjacent_features():
    rows = [
        {"source_atom_id": "roi", "contrast_name": "A", "roi": "motor", "channel": "ch-01", "p_value": 0.01},
        {"source_atom_id": "roi", "contrast_name": "A", "roi": "motor", "channel": "ch-02", "p_value": 0.02},
        {"source_atom_id": "roi", "contrast_name": "A", "roi": "motor", "channel": "ch-05", "p_value": 0.03},
        {"source_atom_id": "roi", "contrast_name": "A", "roi": "motor", "channel": "ch-06", "p_value": 0.20},
    ]
    clusters = summarize_cluster_inference(rows, alpha=0.05)

    assert [cluster["cluster_size"] for cluster in clusters] == [2, 1]
    assert json.loads(clusters[0]["features"]) == ["ch-01", "ch-02"]


def test_data_manifest_serializes_metadata_tables(tmp_path):
    from fnirs_flow.data.manifest import MetadataTableReference, load_data_manifest, write_data_manifest

    manifest = DataManifest(
        dataset_id="demo",
        metadata_tables=[MetadataTableReference(path="participants.tsv", sha256="abc")],
    )
    path = write_data_manifest(manifest, tmp_path)
    restored = load_data_manifest(path)

    assert restored.metadata_tables[0].path == "participants.tsv"
    assert json.loads(path.read_text(encoding="utf-8"))["metadata_tables"][0]["sha256"] == "abc"
