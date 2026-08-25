"""Machine-readable project and release acceptance for processed-Hb analyses."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

FROZEN_INPUTS = (
    "fnirs_signal_provenance.csv",
    "analysis_population_manifest.csv",
    "fnirs_events.tsv",
    "contrast_matrix.csv",
)


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _series_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        row.get("fnirs_record_id", ""),
        row.get("model_id", ""),
        row.get("channel", ""),
        row.get("chromophore", ""),
    )


def _reconstruct_contrasts(
    estimates: list[dict[str, str]],
    covariance: list[dict[str, str]],
    contrasts: list[dict[str, str]],
    designs: list[dict[str, str]],
) -> dict[str, Any]:
    betas: dict[tuple[str, str, str, str], dict[str, float]] = defaultdict(dict)
    covariances: dict[tuple[str, str, str, str], dict[tuple[str, str], float]] = defaultdict(dict)
    for row in estimates:
        if row.get("calculation_status") == "success" and row.get("beta"):
            betas[_series_key(row)][row["regressor"]] = float(row["beta"])
    for row in covariance:
        if row.get("calculation_status") == "success" and row.get("covariance"):
            covariances[_series_key(row)][(row["regressor_i"], row["regressor_j"])] = float(row["covariance"])
    regressor_order = {
        (row.get("fnirs_record_id", ""), row.get("model_id", "")): json.loads(row["regressor_names_json"])
        for row in designs
        if row.get("regressor_names_json")
    }
    failures: list[dict[str, str]] = []
    checked = 0
    for row in contrasts:
        if row.get("calculation_status") != "success":
            continue
        key = _series_key(row)
        names = regressor_order.get((key[0], key[1]), [])
        if not names:
            failures.append({"contrast_id": row.get("contrast_id", ""), "reason": "BETA_NOT_FOUND"})
            continue
        try:
            weights = json.loads(row["weights_json"])
            matrix = weights if weights and isinstance(weights[0], list) else [weights]
            beta = [betas[key][name] for name in names]
            exported_covariance = json.loads(row["covariance_json"])
            reconstructed_estimate = [
                sum(weight * value for weight, value in zip(component, beta, strict=True))
                for component in matrix
            ]
            reconstructed_covariance = [
                [
                    sum(
                        matrix[i][a] * covariances[key][(names[a], names[b])] * matrix[j][b]
                        for a in range(len(names))
                        for b in range(len(names))
                    )
                    for j in range(len(matrix))
                ]
                for i in range(len(matrix))
            ]
            exported_estimate = (
                [float(row["estimate"])]
                if row.get("estimate")
                else [float(value) for value in json.loads(row["estimate_json"])]
            )
            values = [
                *(a - b for a, b in zip(reconstructed_estimate, exported_estimate, strict=True)),
                *(
                    reconstructed_covariance[i][j] - float(exported_covariance[i][j])
                    for i in range(len(matrix))
                    for j in range(len(matrix))
                ),
            ]
            if any(not math.isclose(value, 0.0, rel_tol=1e-9, abs_tol=1e-11) for value in values):
                failures.append({"contrast_id": row.get("contrast_id", ""), "reason": "VALUE_MISMATCH"})
            checked += 1
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            failures.append({"contrast_id": row.get("contrast_id", ""), "reason": type(exc).__name__})
    return {"checked": checked, "failures": failures, "passed": checked > 0 and not failures}


def build_processed_hb_acceptance_report(
    project_dir: str | Path,
    *,
    frozen_root: str | Path | None = None,
    package_path: str | Path | None = None,
) -> dict[str, Any]:
    project = Path(project_dir)
    derivatives = project / "derivatives" / "processed_hb_first_level"
    if not derivatives.exists():
        derivatives = project / "compiled" / "derivatives" / "processed_hb_first_level"
    root = Path(frozen_root) if frozen_root else None
    missing_external = [name for name in FROZEN_INPUTS if root is None or not (root / name).exists()]
    provenance = _csv_rows(derivatives / "input_provenance.csv")
    runs = _csv_rows(derivatives / "run_manifest.csv")
    exclusions = _csv_rows(derivatives / "exclusion_manifest.csv")
    estimates = _csv_rows(derivatives / "first_level_glm_estimates.csv")
    covariance = _csv_rows(derivatives / "first_level_glm_covariance.csv")
    contrasts = _csv_rows(derivatives / "first_level_contrasts.csv")
    designs = _csv_rows(derivatives / "design_matrix_manifest.csv")
    analysis_manifest_path = derivatives / "analysis_manifest.json"
    analysis_manifest = (
        json.loads(analysis_manifest_path.read_text(encoding="utf-8")) if analysis_manifest_path.exists() else {}
    )
    preset_path = project / "compiled" / "processed_hb_preset.json"
    if not preset_path.exists():
        preset_path = project / "processed_hb_preset.json"
    preset = json.loads(preset_path.read_text(encoding="utf-8")) if preset_path.exists() else {}
    scientific_frozen = preset.get("scientific_parameters_frozen") is True

    per_estimand: dict[str, Counter[str]] = defaultdict(Counter)
    successful_series = set()
    for row in estimates:
        key = (row.get("record_pair_id", ""), row.get("model_id", ""), row.get("chromophore", ""))
        if row.get("calculation_status") == "success" and row.get("qc_status") == "pass":
            successful_series.add(key)
    for pair, model, chromophore in successful_series:
        per_estimand[f"{model}:{chromophore}"]["succeeded"] += 1
    for row in exclusions:
        model, chromophore = row.get("model_id", ""), row.get("chromophore", "")
        if model and chromophore:
            per_estimand[f"{model}:{chromophore}"]["failed"] += 1
    contrast_reconstruction = _reconstruct_contrasts(estimates, covariance, contrasts, designs)
    artifact_hashes = analysis_manifest.get("output_artifact_sha256", {})
    artifact_hash_failures = []
    for key, expected in artifact_hashes.items():
        path = derivatives / key
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            artifact_hash_failures.append(key)

    paired = defaultdict(set)
    for pair, model, chromophore in successful_series:
        paired[(pair, model)].add(chromophore)
    unpaired = [f"{pair}:{model}" for (pair, model), values in paired.items() if values != {"hbo", "hbr"}]
    header_decisions = [
        row
        for row in exclusions
        if row.get("reason_code") in {"HEADER_POINT_COUNT_MISMATCH", "HEADER_END_TIME_MISMATCH"}
    ]

    package_audit: dict[str, Any] = {
        "provided": bool(package_path),
        "raw_signal_members": [],
        "absolute_path_records": [],
    }
    if package_path:
        with zipfile.ZipFile(package_path) as archive:
            names = archive.namelist()
            package_audit["raw_signal_members"] = [name for name in names if name.upper().endswith("_RE.TXT")]
            absolute_markers = (b":\\", b"C:/", b"/Users/", b"/home/")
            for name in names:
                if name.endswith((".json", ".csv", ".tsv", ".txt")):
                    payload = archive.read(name)
                    if any(marker in payload for marker in absolute_markers):
                        package_audit["absolute_path_records"].append(name)

    checks = {
        "frozen_record_count_644": len(runs) == 644,
        "local_input_count_627": len([row for row in runs if row.get("discovery_status") == "available"]) == 627,
        "provenance_sha256_for_local_inputs": bool(provenance) and all(row.get("sha256") for row in provenance),
        "header_warning_decisions_191": len(header_decisions) == 191
        and all(row.get("status") in {"pass", "warn", "fail"} for row in header_decisions),
        "per_estimand_counts_present": bool(per_estimand),
        "hbo_hbr_pairing": not unpaired,
        "covariance_and_contrasts_present": bool(covariance) and bool(contrasts),
        "contrast_reconstruction": contrast_reconstruction["passed"],
        "output_artifact_hashes": bool(artifact_hashes) and not artifact_hash_failures,
        "portable_raw_data_free_package": bool(package_path)
        and not package_audit["raw_signal_members"]
        and not package_audit["absolute_path_records"],
    }
    blocked = []
    if missing_external:
        blocked.append({"reason_code": "EXTERNAL_FROZEN_INPUTS_MISSING", "artifacts": missing_external})
    if not scientific_frozen:
        blocked.append({"reason_code": "UNFROZEN_CONFIRMATORY_THRESHOLDS", "preset": str(preset_path)})
    status = (
        "pass"
        if all(checks.values()) and not blocked
        else ("blocked_external_input_missing" if missing_external else "fail")
    )
    return {
        "schema_version": "1.0.0",
        "data_branch": "vendor_processed_hb",
        "status": status,
        "release_ready": status == "pass",
        "checks": checks,
        "blocked": blocked,
        "counts": {"runs": len(runs), "provenance": len(provenance), "header_warning_decisions": len(header_decisions)},
        "per_estimand": {key: dict(value) for key, value in sorted(per_estimand.items())},
        "per_contrast_chromophore": analysis_manifest.get("record_pairs_by_contrast_chromophore", {}),
        "contrast_reconstruction": contrast_reconstruction,
        "artifact_hash_failures": artifact_hash_failures,
        "unpaired_successes": unpaired,
        "package_audit": package_audit,
    }


def write_processed_hb_acceptance_report(project_dir: str | Path, output: str | Path, **kwargs: Any) -> Path:
    report = build_processed_hb_acceptance_report(project_dir, **kwargs)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return target
