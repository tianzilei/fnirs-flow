"""Audit existing ds007738 results without requiring an analysis backend."""

from __future__ import annotations

import csv
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from fnirs_flow.filesystem import is_visible_data_file  # noqa: E402

DATASET_ROOT = Path(os.environ.get("FNIRS_DATASET_ROOT", PROJECT_ROOT / "Sample" / "ds007738-download")).resolve()
OUTPUT_DIR = Path(
    os.environ.get("FNIRS_ANALYSIS_OUTPUT", PROJECT_ROOT / "outputs" / "ds007738_full_analysis")
).resolve()
RESULTS_DIR = OUTPUT_DIR / "derivatives" / "run_results"
REPORTS_DIR = OUTPUT_DIR / "derivatives" / "reports"
AUDIT_PATH = OUTPUT_DIR / "analysis_audit.json"
CURRENT_ANALYSIS_VERSION = "2.0"


def analysis_files(root: Path, pattern: str, *, recursive: bool = False) -> list[Path]:
    """Return matching files while ignoring macOS AppleDouble sidecars."""
    candidates = root.rglob(pattern) if recursive else root.glob(pattern)
    return [path for path in candidates if is_visible_data_file(path, root=root)]


def load_results() -> list[dict[str, Any]]:
    results = []
    for path in sorted(analysis_files(RESULTS_DIR, "*_result.json")):
        results.append(json.loads(path.read_text(encoding="utf-8")))
    return results


def count_excluded_trials() -> tuple[int, int]:
    excluded = 0
    files = 0
    for path in analysis_files(DATASET_ROOT, "*_events.tsv", recursive=True):
        with path.open(encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            if not reader.fieldnames or "include" not in reader.fieldnames:
                continue
            files += 1
            for row in reader:
                value = str(row.get("include", "1")).strip().lower()
                if value not in {"1", "true", "yes"}:
                    excluded += 1
    return excluded, files


def report_counts() -> dict[str, int]:
    patterns = {
        "import": "*_desc-import_summary.json",
        "od": "*_desc-od_summary.json",
        "qc": "*_desc-qc_summary.json",
        "motion": "*_desc-motion_report.json",
        "filter": "*_desc-filter_summary.json",
        "hb": "*_desc-hb_summary.json",
        "design": "*_desc-design_matrix_summary.json",
        "glm": "*_desc-glm_summary.json",
    }
    return {name: len(analysis_files(REPORTS_DIR, pattern)) for name, pattern in patterns.items()}


def nonfinite_locations(value: Any, prefix: str = "") -> list[str]:
    """Locate non-finite floats in nested JSON-compatible values."""
    if isinstance(value, float):
        return [prefix or "$"] if not math.isfinite(value) else []
    if isinstance(value, dict):
        locations = []
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            locations.extend(nonfinite_locations(item, child))
        return locations
    if isinstance(value, list):
        locations = []
        for index, item in enumerate(value):
            locations.extend(nonfinite_locations(item, f"{prefix}[{index}]"))
        return locations
    return []


def channel_numeric_issues(results: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Check completed channel outputs for missing files and non-finite numeric cells."""
    missing_files = []
    nonfinite_cells = []
    for result in results:
        if result.get("status") != "completed":
            continue
        stored_path = str((result.get("channel_summary") or {}).get("channel_csv", ""))
        path = Path(stored_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not stored_path or not path.is_file():
            missing_files.append(str(result.get("run_id")))
            continue
        with path.open(newline="", encoding="utf-8") as stream:
            for row_number, row in enumerate(csv.DictReader(stream), start=2):
                for column, value in row.items():
                    if value in {None, ""}:
                        continue
                    try:
                        numeric = float(value)
                    except ValueError:
                        continue
                    if not math.isfinite(numeric):
                        nonfinite_cells.append(f"{result.get('run_id')}:{row_number}:{column}")
    return missing_files, nonfinite_cells


def audit() -> dict[str, Any]:
    results = load_results()
    source_runs = analysis_files(DATASET_ROOT, "*_nirs.snirf", recursive=True)
    statuses = Counter(str(result.get("status", "unknown")) for result in results)
    completed = [result for result in results if result.get("status") == "completed"]
    excluded_trials, include_files = count_excluded_trials()

    versions = Counter(str(result.get("analysis_version", "legacy")) for result in results)
    reversed_runs = [
        result.get("run_id")
        for result in completed
        if any(
            "_Right_minus_" in name and name.endswith("_Left")
            for name in (result.get("glm") or {}).get("contrasts", [])
        )
    ]
    nonportable_paths = [
        result.get("run_id")
        for result in results
        if "\\" in str(result.get("path", ""))
        or (len(str(result.get("path", ""))) > 1 and str(result.get("path", ""))[1:3] == ":\\")
    ]
    results_without_included_count = [
        result.get("run_id") for result in completed if "included_event_count" not in result
    ]
    nonfinite_result_fields = [
        f"{result.get('run_id')}:{location}"
        for result in results
        for location in nonfinite_locations(result)
    ]
    missing_channel_files, nonfinite_channel_cells = channel_numeric_issues(results)
    readable_results = [result for result in results if result.get("qc")]
    missing_provenance = [result.get("run_id") for result in readable_results if not result.get("provenance")]
    missing_artifacts = [result.get("run_id") for result in readable_results if not result.get("artifacts")]

    actual_reports = report_counts()
    expected_readable = sum(bool(result.get("qc")) for result in results)
    expected_preprocessed = sum(result.get("status") in {"completed", "preprocessed_no_glm"} for result in results)
    expected_reports = {
        "import": expected_readable,
        "od": expected_readable,
        "qc": expected_readable,
        "motion": expected_preprocessed,
        "filter": expected_preprocessed,
        "hb": expected_preprocessed,
        "design": len(completed),
        "glm": len(completed),
    }
    report_mismatches = {
        name: {"actual": actual_reports[name], "expected": expected}
        for name, expected in expected_reports.items()
        if actual_reports[name] != expected
    }

    issues = []
    if len(results) != len(source_runs):
        issues.append("result cardinality does not match source run cardinality")
    if set(versions) != {CURRENT_ANALYSIS_VERSION}:
        issues.append("results were produced by a legacy analysis model")
    if reversed_runs:
        issues.append("contrast direction depends on event order")
    if results_without_included_count and excluded_trials:
        issues.append("results predate include-column trial filtering")
    if report_mismatches:
        issues.append("reportlets were overwritten because task was absent from filenames")
    if nonportable_paths:
        issues.append("stored result paths are machine-specific")
    if nonfinite_result_fields or nonfinite_channel_cells:
        issues.append("analysis outputs contain non-finite numeric values")
    if missing_channel_files:
        issues.append("completed runs are missing channel outputs")
    if missing_provenance or missing_artifacts:
        issues.append("readable runs are missing provenance or artifact records")

    return {
        "dataset": "ds007738-download",
        "source_runs": len(source_runs),
        "result_runs": len(results),
        "status_counts": dict(sorted(statuses.items())),
        "analysis_versions": dict(sorted(versions.items())),
        "excluded_trials_in_source": excluded_trials,
        "event_files_with_include": include_files,
        "reversed_contrast_runs": reversed_runs,
        "completed_without_included_event_count": results_without_included_count,
        "nonportable_path_runs": nonportable_paths,
        "nonfinite_result_fields": nonfinite_result_fields,
        "nonfinite_channel_cells": nonfinite_channel_cells,
        "missing_channel_output_runs": missing_channel_files,
        "missing_provenance_runs": missing_provenance,
        "missing_artifact_runs": missing_artifacts,
        "report_counts": actual_reports,
        "expected_report_counts": expected_reports,
        "report_count_mismatches": report_mismatches,
        "passed": not issues,
        "issues": issues,
        "required_action": (
            "Install fnirs-flow[mne] and rerun scripts/run_ds007738_full_analysis.py" if issues else "none"
        ),
    }


def main() -> int:
    result = audit()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
