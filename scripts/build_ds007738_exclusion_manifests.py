"""Build failure and exclusion manifests from ds007738 v2 analysis results."""

from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fnirs_flow.execution.failures import FailureStore  # noqa: E402
from scripts.run_ds007738_full_analysis import OUTPUT_DIR, analysis_files, portable_path  # noqa: E402

RESULTS_DIR = OUTPUT_DIR / "derivatives" / "run_results"
LOGS_DIR = OUTPUT_DIR / "logs"
EXCLUSION_JSON = LOGS_DIR / "exclusion_manifest.json"
EXCLUSION_CSV = LOGS_DIR / "exclusion_manifest.csv"
SUMMARY_PATH = LOGS_DIR / "exclusion_summary.json"
REPORT_PATH = Path(
    os.environ.get(
        "FNIRS_EXCLUSION_REPORT",
        PROJECT_ROOT / "docs" / "audit" / f"ds007738_exclusion_manifest_{date.today().isoformat()}.md",
    )
).resolve()

EXCLUSION_FIELDS = (
    "exclusion_id",
    "run_id",
    "subject",
    "task",
    "run",
    "category",
    "stage",
    "reason_code",
    "message",
    "source_path",
    "result_path",
    "analysis_version",
    "qc_sci_threshold",
    "qc_min_pass_rate",
    "qc_observed_pass_rate",
    "recoverable",
)


def classify_exclusion(result: dict[str, Any], result_path: Path) -> dict[str, Any] | None:
    """Convert a non-completed analysis result to an explicit exclusion record."""
    status = str(result.get("status", ""))
    if status == "completed":
        return None
    message = str(result.get("message") or result.get("error") or "")
    category = "execution_failure"
    stage = "execution"
    reason_code = "UNEXPECTED_FAILURE"
    recoverable = True
    if status == "qc_failed":
        category = "quality_exclusion"
        stage = "qc_gate"
        reason_code = "SCI_GATE_FAILED"
        recoverable = False
    elif status == "preprocessed_no_glm":
        category = "analysis_not_applicable" if result.get("task") == "resting" else "metadata_exclusion"
        stage = "event_model"
        reason_code = "NO_TASK_EVENTS" if "no task events" in message else "EVENTS_FILE_MISSING"
        recoverable = reason_code == "EVENTS_FILE_MISSING"
    elif status == "data_invalid":
        category = "source_data_invalid"
        stage = "import"
        reason_code = "SNIRF_METADATA_INVALID"
        recoverable = False
    qc = result.get("qc") or {}
    return {
        "exclusion_id": f"exclude-{result.get('run_id')}",
        "run_id": result.get("run_id", ""),
        "subject": result.get("subject", ""),
        "task": result.get("task", ""),
        "run": result.get("run", ""),
        "category": category,
        "stage": stage,
        "reason_code": reason_code,
        "message": message,
        "source_path": result.get("path", ""),
        "result_path": portable_path(result_path),
        "analysis_version": result.get("analysis_version", ""),
        "qc_sci_threshold": qc.get("sci_threshold", ""),
        "qc_min_pass_rate": qc.get("min_sci_pass_rate", ""),
        "qc_observed_pass_rate": qc.get("sci_pass_rate", ""),
        "recoverable": recoverable,
    }


def build_manifests() -> dict[str, Any]:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    exclusions = []
    failure_store = FailureStore()
    total_results = 0
    for path in sorted(analysis_files(RESULTS_DIR, "*_result.json")):
        total_results += 1
        result = json.loads(path.read_text(encoding="utf-8"))
        exclusion = classify_exclusion(result, path)
        if exclusion:
            exclusions.append(exclusion)
        if result.get("status") in {"data_invalid", "failed"}:
            failure_store.register(
                subject=str(result.get("subject", "")),
                run=str(result.get("run", "")),
                atom_id="import" if result.get("status") == "data_invalid" else "execution",
                exception_type=str(result.get("error_type", "RuntimeError")),
                message=str(result.get("message") or result.get("error") or ""),
                recoverable=result.get("status") == "failed",
                log_path=path.relative_to(PROJECT_ROOT).as_posix(),
            )

    EXCLUSION_JSON.write_text(json.dumps(exclusions, indent=2), encoding="utf-8")
    with EXCLUSION_CSV.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=EXCLUSION_FIELDS)
        writer.writeheader()
        writer.writerows(exclusions)
    failure_store.write_json(LOGS_DIR)
    failure_store.write_csv(LOGS_DIR)

    category_counts = Counter(item["category"] for item in exclusions)
    reason_counts = Counter(item["reason_code"] for item in exclusions)
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "ds007738-download",
        "total_results": total_results,
        "included_runs": total_results - len(exclusions),
        "excluded_runs": len(exclusions),
        "failure_records": len(failure_store.all()),
        "category_counts": dict(sorted(category_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "passed": total_results == 223 and len(exclusions) == 168 and len(failure_store.all()) == 1,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(summary)
    return summary


def write_report(summary: dict[str, Any]) -> None:
    rows = ["| Reason code | Run count |", "|---|---:|"]
    rows.extend(f"| {reason} | {count} |" for reason, count in summary["reason_counts"].items())
    text = f"""# ds007738 Exclusion and Failure Manifest

Generated: {summary['created_at']}

- Total runs: {summary['total_results']}
- Included in GLM: {summary['included_runs']}
- Excluded or not applicable: {summary['excluded_runs']}
- True read/execution failure records: {summary['failure_records']}

{chr(10).join(rows)}

`qc_failed` is recorded as a quality exclusion, not disguised as a software
execution failure. Resting-state runs without task events are recorded as not
applicable for the analysis. Missing events files and corrupted SNIRF metadata
retain separate reason codes.

Machine-readable manifests are stored under `outputs/ds007738_full_analysis/logs/`.
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(text, encoding="utf-8")


def main() -> int:
    summary = build_manifests()
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
