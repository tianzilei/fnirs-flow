"""Recompute ds007738 SCI values and quantify QC-gate sensitivity."""

from __future__ import annotations

import csv
import json
import os
import platform
import sys
import time
import warnings
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_ds007738_full_analysis import (  # noqa: E402
    OUTPUT_DIR,
    analysis_files,
    configure_environment,
    discover_runs,
    inspect_snirf_read_failure,
)

SENSITIVITY_DIR = Path(
    os.environ.get("FNIRS_QC_SENSITIVITY_OUTPUT", OUTPUT_DIR / "qc_sensitivity")
).resolve()
RUNS_PATH = SENSITIVITY_DIR / "run_sensitivity.json"
PROGRESS_PATH = SENSITIVITY_DIR / "progress.jsonl"
SUMMARY_PATH = SENSITIVITY_DIR / "qc_sensitivity_summary.json"
MATRIX_PATH = SENSITIVITY_DIR / "qc_gate_matrix.csv"
REPORT_PATH = Path(
    os.environ.get(
        "FNIRS_QC_SENSITIVITY_REPORT",
        PROJECT_ROOT / "docs" / "audit" / f"ds007738_qc_sensitivity_{date.today().isoformat()}.md",
    )
).resolve()

SCI_THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9)
MIN_PASS_RATES = (0.3, 0.5, 0.7)
BASELINE_SCI_THRESHOLD = 0.8
BASELINE_MIN_PASS_RATE = 0.5


def _key(value: float) -> str:
    return f"{value:.1f}"


def summarize_sci(run_id: str, task: str, values: list[float]) -> dict[str, Any]:
    """Build a compact, JSON-safe SCI sensitivity record for one run."""
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not finite.size:
        raise ValueError("SCI computation returned no finite values")
    quantiles = np.quantile(finite, [0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0])
    return {
        "run_id": run_id,
        "task": task,
        "status": "readable",
        "n_channels": int(finite.size),
        "sci_mean": float(finite.mean()),
        "sci_quantiles": {
            name: float(value)
            for name, value in zip(("min", "p05", "p25", "median", "p75", "p95", "max"), quantiles, strict=True)
        },
        "pass_rates": {
            _key(threshold): float(np.mean(finite >= threshold)) for threshold in SCI_THRESHOLDS
        },
    }


def gate_matrix(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Count readable runs passing every threshold/gate combination."""
    readable = [record for record in records if record.get("status") == "readable"]
    rows = []
    for threshold in SCI_THRESHOLDS:
        rates = np.asarray([record["pass_rates"][_key(threshold)] for record in readable], dtype=float)
        for min_pass_rate in MIN_PASS_RATES:
            passed = rates >= min_pass_rate
            rows.append(
                {
                    "sci_threshold": threshold,
                    "min_pass_rate": min_pass_rate,
                    "passed_runs": int(passed.sum()),
                    "failed_runs": int((~passed).sum()),
                    "readable_runs": len(readable),
                    "pass_fraction": float(passed.mean()) if passed.size else 0.0,
                }
            )
    return rows


def task_gate_counts(
    records: list[dict[str, Any]], threshold: float, min_pass_rate: float
) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        task = str(record.get("task", ""))
        if record.get("status") != "readable":
            counts[task]["data_invalid"] += 1
            continue
        passed = float(record["pass_rates"][_key(threshold)]) >= min_pass_rate
        counts[task]["passed" if passed else "failed"] += 1
    return {task: dict(sorted(statuses.items())) for task, statuses in sorted(counts.items())}


def load_existing_records() -> dict[str, dict[str, Any]]:
    if not RUNS_PATH.exists():
        return {}
    records = json.loads(RUNS_PATH.read_text(encoding="utf-8"))
    return {str(record["run_id"]): record for record in records}


def compute_records() -> list[dict[str, Any]]:
    from fnirs_flow.adapters.mne_nirs_adapter import MneNirsAdapter

    existing = load_existing_records()
    runs = discover_runs()
    SENSITIVITY_DIR.mkdir(parents=True, exist_ok=True)
    for index, run in enumerate(runs, start=1):
        if run.run_id in existing:
            continue
        print(f"[{index}/{len(runs)}] {run.run_id}", flush=True)
        started = time.time()
        try:
            adapter = MneNirsAdapter(subject=run.subject, task=run.task, run=run.run, outdir=SENSITIVITY_DIR)
            raw = adapter.read_run(run.path)
            raw_od = adapter.to_optical_density(raw)
            qc = adapter.compute_qc(raw_od, sci_threshold=BASELINE_SCI_THRESHOLD)
            record = summarize_sci(run.run_id, run.task, qc.get("sci_values", []))
        except Exception as exc:
            invalid = inspect_snirf_read_failure(Path(run.path), exc)
            record = {
                "run_id": run.run_id,
                "task": run.task,
                "status": "data_invalid" if invalid else "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "snirf_validation": invalid,
            }
        record["elapsed_seconds"] = round(time.time() - started, 3)
        existing[run.run_id] = record
        ordered = [existing[item.run_id] for item in runs if item.run_id in existing]
        RUNS_PATH.write_text(json.dumps(ordered, indent=2), encoding="utf-8")
        with PROGRESS_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"run_id": run.run_id, "status": record["status"]}) + "\n")
    return [existing[run.run_id] for run in runs]


def write_outputs(records: list[dict[str, Any]]) -> dict[str, Any]:
    import mne
    import mne_bids
    import mne_nirs

    matrix = gate_matrix(records)
    with MATRIX_PATH.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(matrix[0]))
        writer.writeheader()
        writer.writerows(matrix)

    baseline = next(
        row
        for row in matrix
        if row["sci_threshold"] == BASELINE_SCI_THRESHOLD
        and row["min_pass_rate"] == BASELINE_MIN_PASS_RATE
    )
    original_results = []
    results_dir = OUTPUT_DIR / "derivatives" / "run_results"
    for path in analysis_files(results_dir, "*_result.json"):
        original_results.append(json.loads(path.read_text(encoding="utf-8")))
    original_gate_passes = sum(
        result.get("status") in {"completed", "preprocessed_no_glm"} for result in original_results
    )
    readable = [record for record in records if record.get("status") == "readable"]
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "ds007738-download",
        "versions": {
            "python": platform.python_version(),
            "mne": mne.__version__,
            "mne_nirs": mne_nirs.__version__,
            "mne_bids": mne_bids.__version__,
            "numpy": np.__version__,
        },
        "total_runs": len(records),
        "readable_runs": len(readable),
        "status_counts": dict(sorted(Counter(record["status"] for record in records).items())),
        "thresholds": list(SCI_THRESHOLDS),
        "minimum_pass_rates": list(MIN_PASS_RATES),
        "gate_matrix": matrix,
        "baseline": baseline,
        "baseline_task_counts": task_gate_counts(records, BASELINE_SCI_THRESHOLD, BASELINE_MIN_PASS_RATE),
        "baseline_matches_full_analysis": baseline["passed_runs"] == original_gate_passes,
        "full_analysis_gate_passes": original_gate_passes,
        "run_sci_mean": {
            "mean": float(np.mean([record["sci_mean"] for record in readable])),
            "std": float(np.std([record["sci_mean"] for record in readable])),
            "min": float(np.min([record["sci_mean"] for record in readable])),
            "max": float(np.max([record["sci_mean"] for record in readable])),
        },
        "recommendation": (
            "Keep the prespecified SCI >= 0.8 and >=50% channel gate as the primary analysis; "
            "treat alternative gates as sensitivity analyses until an evidence-backed protocol is approved."
        ),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(summary)
    return summary


def write_report(summary: dict[str, Any]) -> None:
    matrix_rows = [
        "| SCI threshold | Minimum channel pass rate | Passed runs | Failed runs | Pass fraction |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in summary["gate_matrix"]:
        matrix_rows.append(
            f"| {row['sci_threshold']:.1f} | {row['min_pass_rate']:.1f} | "
            f"{row['passed_runs']} | {row['failed_runs']} | {row['pass_fraction']:.1%} |"
        )
    task_rows = ["| Task | Passed | Failed | Data invalid |", "|---|---:|---:|---:|"]
    for task, counts in summary["baseline_task_counts"].items():
        task_rows.append(
            f"| {task} | {counts.get('passed', 0)} | {counts.get('failed', 0)} | "
            f"{counts.get('data_invalid', 0)} |"
        )
    text = f"""# ds007738 QC Sensitivity Analysis

Generated: {summary['created_at']}

## Conclusion

- Checked {summary['total_runs']} runs; {summary['readable_runs']} were readable.
- The prespecified primary analysis gate (SCI >= 0.8 and at least 50% passing
  channels) retains {summary['baseline']['passed_runs']} runs and excludes
  {summary['baseline']['failed_runs']} runs.
- Recomputed results match the full-analysis gate results: {summary['baseline_matches_full_analysis']}.
- Lowering thresholds only to increase sample size is not recommended. Alternative
  gates should be treated as sensitivity analyses and disclosed in interpretation.

## Gate Sensitivity Matrix

{chr(10).join(matrix_rows)}

## Task Distribution Under the Primary Analysis Gate

{chr(10).join(task_rows)}

## Runtime Environment

```json
{json.dumps(summary['versions'], indent=2)}
```

Machine-readable results are stored under `outputs/ds007738_full_analysis/qc_sensitivity/`.
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(text, encoding="utf-8")


def main() -> int:
    configure_environment()
    warnings.filterwarnings("ignore", message="Extraction of measurement date from SNIRF file failed.*")
    warnings.filterwarnings("ignore", message="Negative intensities encountered.*")
    records = compute_records()
    summary = write_outputs(records)
    print(json.dumps(summary, indent=2))
    return 0 if summary["baseline_matches_full_analysis"] and not summary["status_counts"].get("failed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
