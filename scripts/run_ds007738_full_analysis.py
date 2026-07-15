"""Full resumable analysis for the local ds007738 BIDS-NIRS dataset."""

from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DATASET_ROOT = Path(os.environ.get("FNIRS_DATASET_ROOT", PROJECT_ROOT / "Sample" / "ds007738-download")).resolve()
OUTPUT_DIR = Path(
    os.environ.get("FNIRS_ANALYSIS_OUTPUT", PROJECT_ROOT / "outputs" / "ds007738_full_analysis")
).resolve()
REPORTS_DIR = OUTPUT_DIR / "derivatives" / "reports"
RUN_RESULTS_DIR = OUTPUT_DIR / "derivatives" / "run_results"
CHANNEL_DIR = OUTPUT_DIR / "derivatives" / "channel_results"
SUMMARY_PATH = OUTPUT_DIR / "analysis_report.json"
PROGRESS_PATH = OUTPUT_DIR / "progress.jsonl"
MIGRATION_MARKER = OUTPUT_DIR / ".analysis_v2_initialized"
SCI_THRESHOLD = 0.8
MIN_SCI_PASS_RATE = 0.5
MAX_RUNS = int(os.environ.get("FNIRS_MAX_RUNS", "0") or "0")
ANALYSIS_VERSION = "2.0"


def analysis_files(root: Path, pattern: str, *, recursive: bool = False) -> list[Path]:
    """Return matching files while ignoring macOS AppleDouble sidecars."""
    candidates = root.rglob(pattern) if recursive else root.glob(pattern)
    return [
        path
        for path in candidates
        if path.is_file() and not any(part.startswith("._") for part in path.relative_to(root).parts)
    ]


def portable_path(path: Path | str) -> str:
    """Store paths relative to the project when possible and always use POSIX separators."""
    candidate = Path(path).resolve()
    try:
        return candidate.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return candidate.as_posix()


def resolve_stored_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


@dataclass
class RunRecord:
    subject: str
    task: str
    run: str
    relative_path: str
    path: str
    events_path: str

    @property
    def run_id(self) -> str:
        run_part = f"_run-{self.run}" if self.run else ""
        return f"sub-{self.subject}_task-{self.task}{run_part}"


def configure_environment() -> None:
    mne_home = PROJECT_ROOT / ".tmp" / "mne"
    mne_home.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("_MNE_FAKE_HOME_DIR", str(mne_home))
    os.environ.setdefault("MNE_HOME", str(mne_home))
    os.environ.setdefault("MNE_DONTWRITE_HOME", "true")
    os.environ.setdefault("MPLBACKEND", "Agg")


def parse_entities(path: Path) -> dict[str, str]:
    entities: dict[str, str] = {}
    for part in path.stem.split("_"):
        if "-" not in part:
            continue
        key, value = part.split("-", 1)
        if key in {"sub", "task", "run"}:
            entities[key] = value
    if "sub" not in entities:
        for parent in path.parents:
            if parent.name.startswith("sub-"):
                entities["sub"] = parent.name[4:]
                break
    return entities


def find_events_path(snirf_path: Path) -> Path | None:
    direct = snirf_path.with_name(snirf_path.name.replace("_nirs.snirf", "_events.tsv"))
    return direct if direct.exists() else None


def discover_runs() -> list[RunRecord]:
    runs: list[RunRecord] = []
    for snirf_path in sorted(analysis_files(DATASET_ROOT, "*_nirs.snirf", recursive=True)):
        entities = parse_entities(snirf_path)
        events_path = find_events_path(snirf_path)
        runs.append(
            RunRecord(
                subject=entities.get("sub", ""),
                task=entities.get("task", ""),
                run=entities.get("run", ""),
                relative_path=snirf_path.relative_to(DATASET_ROOT).as_posix(),
                path=str(snirf_path),
                events_path=str(events_path) if events_path else "",
            )
        )
    if MAX_RUNS:
        runs = runs[:MAX_RUNS]
    return runs


def run_result_path(run: RunRecord) -> Path:
    return RUN_RESULTS_DIR / f"{run.run_id}_result.json"


def channel_csv_path(run: RunRecord) -> Path:
    return CHANNEL_DIR / f"{run.run_id}_channels.csv"


def inspect_snirf_read_failure(path: Path, exc: Exception) -> dict[str, Any] | None:
    """Return data-invalid details for known malformed SNIRF read failures."""
    message = str(exc)
    if type(exc).__name__ != "TypeError" or "0-d array" not in message:
        return None
    try:
        import h5py
    except ImportError:
        return None

    details: dict[str, Any] = {"reader_error": message}
    try:
        with h5py.File(path, "r") as h5:
            nirs = h5.get("nirs")
            if nirs is None:
                details["missing_groups"] = ["/nirs"]
                return details

            missing_groups = []
            if "probe" not in nirs:
                missing_groups.append("/nirs/probe")
            if missing_groups:
                details["missing_groups"] = missing_groups

            data1 = nirs.get("data1")
            scalar_wavelength_actual = 0
            measurement_lists = 0
            if data1 is not None:
                for name, group in data1.items():
                    if not name.startswith("measurementList"):
                        continue
                    measurement_lists += 1
                    wavelength_actual = group.get("wavelengthActual")
                    if wavelength_actual is not None and wavelength_actual.shape == ():
                        scalar_wavelength_actual += 1
            details["measurement_list_count"] = measurement_lists
            details["scalar_wavelength_actual_count"] = scalar_wavelength_actual
    except Exception as inspect_exc:
        details["inspection_error"] = f"{type(inspect_exc).__name__}: {inspect_exc}"

    if details.get("missing_groups") or details.get("scalar_wavelength_actual_count", 0):
        details["classification_reason"] = "SNIRF metadata are structurally incomplete for the MNE SNIRF reader."
        return details
    return None


def sanitize_trial_type(value: Any) -> str:
    text = str(value).strip()
    return text if text and text.lower() != "nan" else ""


def load_task_events(run: RunRecord, raw_hb: Any) -> tuple[np.ndarray, dict[str, int], dict[str, int]]:
    if not run.events_path:
        raise ValueError("events.tsv not found")
    events_path = Path(run.events_path)
    df = pd.read_csv(events_path, sep="\t")
    if "trial_type" not in df.columns or "onset" not in df.columns:
        raise ValueError(f"events.tsv lacks required columns: {events_path}")
    if "include" in df.columns:
        include = df["include"].astype(str).str.strip().str.lower()
        df = df[include.isin({"1", "true", "yes"})].copy()
    df["trial_type"] = df["trial_type"].map(sanitize_trial_type)
    df = df[df["trial_type"] != ""].copy()
    if df.empty:
        raise ValueError("no task events after removing blank trial_type rows")
    if "duration" not in df.columns:
        df["duration"] = 5.0
    if "value" not in df.columns:
        df["value"] = np.arange(1, len(df) + 1)

    event_id: dict[str, int] = {}
    next_id = 1
    codes: list[int] = []
    for trial_type in df["trial_type"].astype(str):
        if trial_type not in event_id:
            event_id[trial_type] = next_id
            next_id += 1
        codes.append(event_id[trial_type])

    sfreq = float(raw_hb.info["sfreq"])
    events = np.column_stack(
        [
            (df["onset"].to_numpy(dtype=float) * sfreq).astype(int),
            np.maximum(
                1,
                np.rint(df["duration"].to_numpy(dtype=float) * sfreq).astype(int),
            ),
            np.asarray(codes, dtype=int),
        ]
    )
    event_counts = Counter(df["trial_type"].astype(str))
    return events, event_id, dict(sorted(event_counts.items()))


def qc_summary(qc: dict[str, Any]) -> dict[str, Any]:
    sci_values = np.asarray(qc.get("sci_values", []), dtype=float)
    pass_rate = float(np.mean(sci_values >= SCI_THRESHOLD)) if sci_values.size else 0.0
    return {
        "sci_mean": qc.get("sci_mean"),
        "sci_min": qc.get("sci_min"),
        "sci_pass_rate": pass_rate,
        "n_channels": qc.get("n_channels"),
        "n_short_channels": qc.get("n_short_channels"),
        "sd_distance_mean": qc.get("sd_distance_mean"),
        "sci_threshold": SCI_THRESHOLD,
        "qc_gate_passed": pass_rate >= MIN_SCI_PASS_RATE,
        "min_sci_pass_rate": MIN_SCI_PASS_RATE,
    }


def build_contrasts(event_id: dict[str, int]) -> list[dict[str, Any]]:
    """Build deterministic contrasts independent of first-event ordering."""
    conditions = list(event_id.keys())
    contrasts: list[dict[str, Any]] = []
    if len(conditions) == 2:
        canonical = sorted(conditions, key=lambda value: value.casefold())
        positive, negative = canonical
        left = next((value for value in conditions if value.casefold().endswith(" left")), None)
        right = next((value for value in conditions if value.casefold().endswith(" right")), None)
        if left and right:
            positive, negative = left, right
        weights = [0.0] * (len(conditions) + 1)
        weights[conditions.index(positive)] = 1.0
        weights[conditions.index(negative)] = -1.0
        contrasts.append(
            {
                "name": f"{positive}_minus_{negative}".replace(" ", "_"),
                "weights": weights,
            }
        )
    else:
        for idx, condition in enumerate(conditions):
            weights = [0.0] * (len(conditions) + 1)
            weights[idx] = 1.0
            contrasts.append({"name": condition.replace(" ", "_"), "weights": weights})
    return contrasts


def summarize_channel_results(run: RunRecord, channel_results: dict[str, Any]) -> dict[str, Any]:
    rows = channel_results.get("channels", [])
    if not rows:
        return {"n_channels": 0}
    CHANNEL_DIR.mkdir(parents=True, exist_ok=True)
    keys = [key for key in rows[0] if key != "channel_idx"]
    path = channel_csv_path(run)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["channel_idx", *keys])
        for row in rows:
            writer.writerow([row.get("channel_idx", ""), *[row.get(key, "") for key in keys]])
    summary: dict[str, Any] = {
        "n_channels": len(rows),
        "channel_csv": portable_path(path),
    }
    for key in keys:
        vals = np.asarray([row.get(key, np.nan) for row in rows], dtype=float)
        vals = vals[np.isfinite(vals)]
        if vals.size:
            summary[key] = {
                "mean": float(vals.mean()),
                "std": float(vals.std()),
                "min": float(vals.min()),
                "max": float(vals.max()),
            }
    return summary


def process_run(run: RunRecord, index: int, total: int) -> dict[str, Any]:
    from fnirs_flow.adapters.mne_nirs_adapter import MneNirsAdapter

    result_path = run_result_path(run)
    if result_path.exists():
        existing = json.loads(result_path.read_text(encoding="utf-8"))
        if existing.get("status") != "failed" and existing.get("analysis_version") == ANALYSIS_VERSION:
            return existing

    print(f"[{index}/{total}] {run.run_id}", flush=True)
    adapter = MneNirsAdapter(
        subject=run.subject,
        task=run.task,
        run=run.run,
        outdir=REPORTS_DIR,
    )
    payload: dict[str, Any] = {
        "run_id": run.run_id,
        "analysis_version": ANALYSIS_VERSION,
        "subject": run.subject,
        "task": run.task,
        "run": run.run,
        "relative_path": run.relative_path,
        "path": portable_path(run.path),
        "events_path": portable_path(run.events_path) if run.events_path else "",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    t0 = time.time()
    try:
        raw = adapter.read_run(run.path)
        raw_od = adapter.to_optical_density(raw)
        qc = adapter.compute_qc(raw_od, sci_threshold=SCI_THRESHOLD)
        qcs = qc_summary(qc)
        payload.update(
            {
                "status": "preprocessed",
                "n_raw_channels": len(raw.ch_names),
                "n_times": len(raw.times),
                "sfreq": float(raw.info.get("sfreq", 0)),
                "duration_s": float(raw.times[-1]) if len(raw.times) else 0.0,
                "qc": qcs,
            }
        )

        if not qcs["qc_gate_passed"]:
            payload.update({"status": "qc_failed", "message": "SCI gate failed; GLM skipped"})
            return payload

        raw_mc = adapter.apply_motion_correction(raw_od, method="tddr")
        raw_filt = adapter.apply_filter(raw_mc, l_freq=0.01, h_freq=0.2, method="bandpass")
        raw_hb = adapter.to_haemoglobin(raw_filt, ppf=6.0)

        try:
            events, event_id, event_counts = load_task_events(run, raw_hb)
        except Exception as exc:
            payload.update(
                {
                    "status": "preprocessed_no_glm",
                    "message": str(exc),
                    "n_hb_channels": len(raw_hb.ch_names),
                }
            )
            return payload

        design = adapter.build_design_matrix(raw_hb, events, event_id)
        glm_result = adapter.fit_first_level_glm(raw_hb, design, noise_model="ols")
        contrast_result = adapter.estimate_contrast(glm_result, build_contrasts(event_id))
        channel_results = adapter.channel_output(contrast_result)
        channel_summary = summarize_channel_results(run, channel_results)
        payload.update(
            {
                "status": "completed",
                "n_hb_channels": len(raw_hb.ch_names),
                "event_id": event_id,
                "event_counts": event_counts,
                "included_event_count": int(sum(event_counts.values())),
                "glm": {
                    "conditions": glm_result.get("conditions", []),
                    "df": glm_result.get("df"),
                    "noise_model": glm_result.get("noise_model"),
                    "contrasts": [c.get("name") for c in contrast_result.get("contrasts", [])],
                },
                "channel_summary": channel_summary,
            }
        )
    except Exception as exc:
        invalid_details = inspect_snirf_read_failure(Path(run.path), exc)
        if invalid_details:
            payload.update(
                {
                    "status": "data_invalid",
                    "message": "SNIRF file could not be read because required metadata are malformed or missing.",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "snirf_validation": invalid_details,
                }
            )
        else:
            payload.update(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
    finally:
        payload["elapsed_seconds"] = round(time.time() - t0, 3)
        payload["finished_at"] = datetime.now(timezone.utc).isoformat()
        payload["artifacts"] = [artifact.model_dump() for artifact in adapter.artifacts.all()]
        payload["provenance"] = adapter.provenance.all()
        RUN_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        with PROGRESS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"run_id": run.run_id, "status": payload["status"]}) + "\n")
    return payload


def validate_analysis(results: list[dict[str, Any]], total_runs: int) -> dict[str, Any]:
    """Check result cardinality, paths, contrasts, and collision-safe reportlets."""
    errors: list[str] = []
    warnings: list[str] = []
    run_ids = [str(result.get("run_id", "")) for result in results]
    if len(run_ids) != len(set(run_ids)):
        errors.append("duplicate run_id values in result set")
    if len(results) != total_runs:
        errors.append(f"processed {len(results)} of {total_runs} runs")

    missing_sources = [
        result.get("run_id")
        for result in results
        if result.get("path") and not resolve_stored_path(str(result["path"])).exists()
    ]
    if missing_sources:
        errors.append(f"{len(missing_sources)} stored source paths do not resolve")

    completed = [result for result in results if result.get("status") == "completed"]
    noncanonical = []
    missing_channel_csv = []
    for result in completed:
        names = (result.get("glm") or {}).get("contrasts", [])
        if any("_Right_minus_" in name and name.endswith("_Left") for name in names):
            noncanonical.append(result.get("run_id"))
        channel_csv = str((result.get("channel_summary") or {}).get("channel_csv", ""))
        if not channel_csv or not resolve_stored_path(channel_csv).exists():
            missing_channel_csv.append(result.get("run_id"))
    if noncanonical:
        errors.append(f"{len(noncanonical)} completed runs use reversed right-minus-left contrasts")
    if missing_channel_csv:
        errors.append(f"{len(missing_channel_csv)} completed runs lack channel CSV output")

    expected_readable = sum(bool(result.get("qc")) for result in results)
    expected_preprocessed = sum(result.get("status") in {"completed", "preprocessed_no_glm"} for result in results)
    expected_completed = len(completed)
    report_counts = {
        "import": len(analysis_files(REPORTS_DIR, "*_desc-import_summary.json")),
        "od": len(analysis_files(REPORTS_DIR, "*_desc-od_summary.json")),
        "qc": len(analysis_files(REPORTS_DIR, "*_desc-qc_summary.json")),
        "motion": len(analysis_files(REPORTS_DIR, "*_desc-motion_report.json")),
        "filter": len(analysis_files(REPORTS_DIR, "*_desc-filter_summary.json")),
        "hb": len(analysis_files(REPORTS_DIR, "*_desc-hb_summary.json")),
        "design": len(analysis_files(REPORTS_DIR, "*_desc-design_matrix_summary.json")),
        "glm": len(analysis_files(REPORTS_DIR, "*_desc-glm_summary.json")),
    }
    expected_counts = {
        "import": expected_readable,
        "od": expected_readable,
        "qc": expected_readable,
        "motion": expected_preprocessed,
        "filter": expected_preprocessed,
        "hb": expected_preprocessed,
        "design": expected_completed,
        "glm": expected_completed,
    }
    for kind, expected in expected_counts.items():
        if report_counts[kind] != expected:
            errors.append(f"{kind} report count is {report_counts[kind]}, expected {expected}")

    no_glm = [result for result in results if result.get("status") == "preprocessed_no_glm"]
    if no_glm:
        warnings.append(f"{len(no_glm)} runs were preprocessed but had no usable task events")
    invalid = [result for result in results if result.get("status") == "data_invalid"]
    if invalid:
        warnings.append(f"{len(invalid)} source runs are structurally invalid")

    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "report_counts": report_counts,
        "expected_report_counts": expected_counts,
        "missing_source_runs": missing_sources,
        "noncanonical_contrast_runs": noncanonical,
        "missing_channel_csv_runs": missing_channel_csv,
    }


def write_summary(results: list[dict[str, Any]], total_runs: int, elapsed: float) -> None:
    status_counts = Counter(r.get("status", "unknown") for r in results)
    task_status: dict[str, Counter[str]] = defaultdict(Counter)
    qc_pass_rates: list[float] = []
    completed_contrasts: dict[str, list[float]] = defaultdict(list)
    invalid_runs = []

    for result in results:
        task_status[result.get("task", "")][result.get("status", "unknown")] += 1
        if result.get("status") == "data_invalid":
            invalid_runs.append(
                {
                    "run_id": result.get("run_id"),
                    "relative_path": result.get("relative_path"),
                    "message": result.get("message"),
                    "snirf_validation": result.get("snirf_validation"),
                }
            )
        qc = result.get("qc") or {}
        if "sci_pass_rate" in qc:
            qc_pass_rates.append(float(qc["sci_pass_rate"]))
        channel_summary = result.get("channel_summary") or {}
        for key, value in channel_summary.items():
            if isinstance(value, dict) and "mean" in value:
                completed_contrasts[key].append(float(value["mean"]))

    contrast_summary = {
        key: {
            "n_runs": len(values),
            "mean_of_run_means": float(np.mean(values)),
            "std_of_run_means": float(np.std(values)),
        }
        for key, values in sorted(completed_contrasts.items())
    }
    summary = {
        "dataset": "ds007738-download",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_runs": total_runs,
        "processed_results": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "task_status_counts": {task: dict(counter) for task, counter in sorted(task_status.items())},
        "qc": {
            "sci_threshold": SCI_THRESHOLD,
            "min_sci_pass_rate": MIN_SCI_PASS_RATE,
            "mean_sci_pass_rate": float(np.mean(qc_pass_rates)) if qc_pass_rates else None,
            "std_sci_pass_rate": float(np.std(qc_pass_rates)) if qc_pass_rates else None,
        },
        "contrast_summary": contrast_summary,
        "invalid_runs": invalid_runs,
        "validation": validate_analysis(results, total_runs),
        "analysis_version": ANALYSIS_VERSION,
        "run_results_dir": portable_path(RUN_RESULTS_DIR),
        "channel_results_dir": portable_path(CHANNEL_DIR),
        "elapsed_seconds": round(elapsed, 3),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")


def main() -> int:
    configure_environment()
    t0 = time.time()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    previous_version = ""
    if SUMMARY_PATH.exists():
        try:
            previous_version = json.loads(SUMMARY_PATH.read_text(encoding="utf-8")).get("analysis_version", "")
        except (json.JSONDecodeError, OSError):
            previous_version = ""
    if previous_version != ANALYSIS_VERSION:
        try:
            import mne  # noqa: F401
        except ImportError:
            print(
                "Analysis v2 requires MNE-Python before existing outputs can be migrated. "
                "Install fnirs-flow[mne] and rerun; existing v1 outputs were left unchanged.",
                flush=True,
            )
            return 2
        if not MIGRATION_MARKER.exists():
            PROGRESS_PATH.unlink(missing_ok=True)
            if REPORTS_DIR.exists() and any(REPORTS_DIR.iterdir()):
                archive = REPORTS_DIR.with_name(f"reports_v{previous_version or 'legacy'}_collided")
                if archive.exists():
                    shutil.rmtree(archive)
                REPORTS_DIR.rename(archive)
            MIGRATION_MARKER.write_text(ANALYSIS_VERSION, encoding="utf-8")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    RUN_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CHANNEL_DIR.mkdir(parents=True, exist_ok=True)

    runs = discover_runs()
    results = []
    for idx, run in enumerate(runs, start=1):
        result = process_run(run, idx, len(runs))
        results.append(result)
        write_summary(results, len(runs), time.time() - t0)
    write_summary(results, len(runs), time.time() - t0)
    status_counts = Counter(r.get("status", "unknown") for r in results)
    print(f"Full analysis complete: {dict(status_counts)}")
    print(f"Summary: {SUMMARY_PATH}")
    validation = validate_analysis(results, len(runs))
    return 0 if not status_counts.get("failed") and validation["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
