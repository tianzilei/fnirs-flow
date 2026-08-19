"""Reproducible synthetic execution benchmark with auditable JSON output."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from fnirs_flow.data.group_analysis import (  # noqa: E402
    GroupContrastSpec,
    build_group_design_matrix,
    fit_group_glm,
)
from fnirs_flow.execution.concurrency import native_thread_limit  # noqa: E402


def _versions() -> dict[str, str]:
    result = {"python": platform.python_version(), "numpy": np.__version__}
    for name in ("scipy", "mne", "mne_nirs"):
        try:
            module = __import__(name)
            result[name] = str(getattr(module, "__version__", "unknown"))
        except ImportError:
            result[name] = "not-installed"
    return result


def _native_threadpools() -> list[dict[str, Any]]:
    try:
        from threadpoolctl import threadpool_info

        return [
            {
                "internal_api": item.get("internal_api", ""),
                "num_threads": item.get("num_threads", 0),
                "prefix": item.get("prefix", ""),
                "version": item.get("version", ""),
            }
            for item in threadpool_info()
        ]
    except ImportError:
        return []


def _peak_rss_mb() -> float:
    try:
        import psutil

        memory = psutil.Process().memory_info()
        peak = getattr(memory, "peak_wset", memory.rss)
        return float(peak / 1024**2)
    except (ImportError, AttributeError):
        if os.name == "nt":
            return 0.0
        import resource

        return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)


def _run_kernel(payload: tuple[int, int, int, int, int]) -> dict[str, Any]:
    seed, channels, samples, permutations, blas_threads = payload
    rng = np.random.default_rng(seed)
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    io_started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="fnirs-flow-benchmark-") as directory:
        input_path = Path(directory) / "intensity.npy"
        generated = np.abs(rng.normal(loc=1.0, scale=0.1, size=(channels, samples))) + 1e-6
        np.save(input_path, generated)
        data = np.load(input_path)
        read_seconds = time.perf_counter() - io_started

    with native_thread_limit(blas_threads):
        from scipy.signal import butter, sosfiltfilt

        preprocess_started = time.perf_counter()
        optical_density = -np.log(data / np.mean(data, axis=-1, keepdims=True))
        derivative = np.diff(optical_density, prepend=optical_density[:, :1], axis=-1)
        motion_repaired = optical_density - np.median(derivative, axis=-1, keepdims=True)
        sos = butter(4, [0.01 / 5.0, 0.2 / 5.0], btype="band", output="sos")
        filtered = sosfiltfilt(sos, motion_repaired, axis=-1)
        extinction = np.asarray([[1.0, 0.4], [0.3, 1.0]], dtype=float)
        paired = filtered[: channels - (channels % 2)].reshape(-1, 2, samples)
        haemoglobin = np.einsum("ab,cbt->cat", np.linalg.pinv(extinction), paired).reshape(-1, samples)
        preprocess_seconds = time.perf_counter() - preprocess_started

        first_level_started = time.perf_counter()
        time_axis = np.linspace(0.0, 1.0, samples)
        design_matrix = np.column_stack(
            [np.ones(samples), np.sin(2 * np.pi * time_axis), np.cos(2 * np.pi * time_axis)]
        )
        betas = np.linalg.pinv(design_matrix) @ haemoglobin.T
        first_level_contrast = betas[1] - betas[2]
        first_level_seconds = time.perf_counter() - first_level_started

    rows = []
    for subject in range(12):
        group = "control" if subject < 6 else "patient"
        for feature in range(min(channels, 8)):
            rows.append(
                {
                    "participant_id": f"sub-{subject:02d}",
                    "group": group,
                    "channel": f"ch-{feature:02d}",
                    "beta": float(first_level_contrast[feature % len(first_level_contrast)] + subject / 100),
                }
            )
    group_started = time.perf_counter()
    with native_thread_limit(blas_threads):
        design = build_group_design_matrix(rows, design_type="two_sample_t")
        contrast = GroupContrastSpec(name="group", weights=[-1.0, 1.0])
        glm = fit_group_glm(design, contrasts=[contrast], permutation_count=permutations, random_seed=seed)
    group_seconds = time.perf_counter() - group_started
    result = {
        "filtered_mean": float(filtered.mean()),
        "filtered_std": float(filtered.std()),
        "first_level_contrast": first_level_contrast.tolist(),
        "contrasts": glm.contrasts,
        "corrected": glm.corrected,
    }
    return {
        "seed": seed,
        "result": result,
        "stages": {
            "read_seconds": read_seconds,
            "preprocessing_seconds": preprocess_seconds,
            "first_level_seconds": first_level_seconds,
            "group_seconds": group_seconds,
            "artifact_io_seconds": 0.0,
        },
        "wall_seconds": time.perf_counter() - started_wall,
        "cpu_seconds": time.process_time() - started_cpu,
        "peak_rss_mb": _peak_rss_mb(),
    }


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    payloads = [
        (args.seed + index, args.channels, args.samples, args.permutations, args.blas_threads)
        for index in range(args.runs)
    ]
    if args.backend == "process" and args.run_workers > 1 and args.runs > 1:
        with ProcessPoolExecutor(max_workers=args.run_workers) as pool:
            runs = list(pool.map(_run_kernel, payloads))
        effective_backend, effective_workers = "process", args.run_workers
    else:
        runs = [_run_kernel(payload) for payload in payloads]
        effective_backend, effective_workers = "serial", 1

    deterministic = {
        "schema_version": "1.0.0",
        "workload": {
            "runs": args.runs,
            "channels": args.channels,
            "samples": args.samples,
            "permutation_count": args.permutations,
            "seed": args.seed,
        },
        "execution": {
            "requested_backend": args.backend,
            "effective_backend": effective_backend,
            "run_workers": effective_workers,
            "blas_threads": args.blas_threads,
        },
        "versions": _versions(),
        "native_threadpools": _native_threadpools(),
        "results": [item["result"] for item in runs],
        "status": "completed",
    }
    report = {
        **deterministic,
        "timing": {
            "compute_seconds": sum(item["wall_seconds"] for item in runs),
            "io_seconds": sum(
                item["stages"]["read_seconds"] + item["stages"]["artifact_io_seconds"]
                for item in runs
            ),
            "summary_seconds": max(0.0, time.perf_counter() - started_wall),
            "cpu_seconds": time.process_time() - started_cpu,
            "stages": [item["stages"] for item in runs],
        },
        "peak_rss_mb": _peak_rss_mb(),
        "worker_peak_rss_mb": [item["peak_rss_mb"] for item in runs],
        "conservative_concurrent_rss_mb": (
            sum(sorted((item["peak_rss_mb"] for item in runs), reverse=True)[:effective_workers])
        ),
    }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("serial", "process"), default="serial")
    parser.add_argument("--run-workers", type=int, default=1)
    parser.add_argument("--blas-threads", type=int, default=1)
    parser.add_argument("--runs", type=int, default=4)
    parser.add_argument("--channels", type=int, default=16)
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--permutations", type=int, default=32)
    parser.add_argument("--seed", type=int, default=20260819)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for name in ("run_workers", "blas_threads", "runs", "channels", "samples"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be >= 1")
    return args


if __name__ == "__main__":
    benchmark_args = parse_args()
    benchmark_report = run_benchmark(benchmark_args)
    rendered = json.dumps(benchmark_report, indent=2, sort_keys=True)
    if benchmark_args.output:
        benchmark_args.output.parent.mkdir(parents=True, exist_ok=True)
        benchmark_args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
