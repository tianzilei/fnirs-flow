from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def _benchmark_module():
    path = Path(__file__).parents[1] / "tools" / "benchmark" / "run_execution_benchmark.py"
    spec = importlib.util.spec_from_file_location("run_execution_benchmark", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_benchmark_structured_results_repeat():
    module = _benchmark_module()
    args = argparse.Namespace(
        backend="serial",
        run_workers=1,
        blas_threads=1,
        runs=2,
        channels=4,
        samples=200,
        permutations=2,
        seed=7,
    )
    reports = [module.run_benchmark(args) for _ in range(3)]
    assert reports[0]["results"] == reports[1]["results"] == reports[2]["results"]
    assert all(report["timing"]["compute_seconds"] >= 0 for report in reports)
    assert all(report["timing"]["io_seconds"] > 0 for report in reports)
    assert all(len(report["worker_peak_rss_mb"]) == 2 for report in reports)
    assert set(reports[0]["timing"]["stages"][0]) == {
        "read_seconds",
        "preprocessing_seconds",
        "first_level_seconds",
        "group_seconds",
        "artifact_io_seconds",
    }
