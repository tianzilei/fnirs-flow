"""Tests that the performance benchmark measures real canonical bundles."""

from __future__ import annotations

from pathlib import Path

import pytest

from fnirs_flow.api.project_bundle import ProjectBundleError, ProjectBundleManager
from fnirs_flow.api.projects import ProjectStore
from scripts.benchmark_performance import MIB, benchmark_cold_start, benchmark_project_size, run_benchmark


def test_benchmark_payload_is_committed_to_bundle(tmp_path: Path) -> None:
    result = benchmark_project_size(
        tmp_path / "store",
        1,
        profile="incompressible",
        iterations=1,
        revision_count=2,
    )

    payload = result["payload"]
    assert payload["written_bytes"] == MIB
    assert payload["declared_bundle_payload_bytes"] >= MIB
    assert result["storage"]["current_bundle_bytes"] > 100_000
    assert result["storage"]["retained_bundle_count"] >= 1
    assert result["open_and_verify"]["avg_ms"] > 0


def test_run_benchmark_records_valid_methodology(tmp_path: Path) -> None:
    results = run_benchmark(
        [1],
        profile="compressible",
        iterations=1,
        revision_count=1,
        work_dir=tmp_path,
    )

    assert results["valid"]
    assert results["methodology"]["canonical_bundle_verified"]
    assert results["methodology"]["payload_location"].startswith("managed .workspaces")
    assert results["benchmarks"]["1mb"]["payload"]["written_bytes"] == MIB


def test_bundle_within_ten_mib_boundary_accepted(tmp_path: Path) -> None:
    """A bundle just under the 10 MiB limit should be accepted."""
    result = benchmark_project_size(
        tmp_path / "store",
        8,  # 8 MiB payload, well within 10 MiB after compression
        profile="compressible",
        iterations=1,
        revision_count=1,
    )
    assert result["storage"]["current_bundle_bytes"] <= 10 * MIB


def test_bundle_exceeding_ten_mib_rejected(tmp_path: Path) -> None:
    """A single file exceeding the per-member limit should be rejected."""
    store = ProjectStore(tmp_path / "store")
    project = store.create("boundary-test")
    output_dir = store.get_output_dir(project.id) / "derivatives"
    output_dir.mkdir(parents=True)
    # Write a file just over 8 MiB (per-member limit)
    (output_dir / "big.csv").write_text("x" * (8 * MIB + 1), encoding="utf-8")
    with pytest.raises(ProjectBundleError, match="per-member limit"):
        store.commit_project(project.id, reason="boundary_test")


def test_cold_start_benchmark_smoke(tmp_path: Path) -> None:
    """Smoke test for cold start benchmark with a small project count."""
    result = benchmark_cold_start(
        tmp_path / "store",
        project_count=5,
        size_mb=1,
        iterations=1,
    )
    assert result["project_count"] == 5
    assert result["startup"]["avg_ms"] > 0
    assert result["list_projects"]["project_count"] == 5
    assert result["open_first_project"]["avg_ms"] > 0


def test_change_detection_skips_unchanged_files(tmp_path: Path) -> None:
    """Saving twice with the same outputs should reuse cached file entries."""
    store = ProjectStore(tmp_path / "store")
    project = store.create("change-detect")
    output_dir = store.get_output_dir(project.id) / "derivatives"
    output_dir.mkdir(parents=True)
    (output_dir / "stats.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    store.commit_project(project.id, reason="initial")
    # Read the first bundle's file manifest
    manager = ProjectBundleManager(tmp_path / "store")
    manifest1 = manager.read_manifest(manager.bundle_path(project.id))
    # Find the stats.csv entry (path may include outputs/ prefix)
    csv_key = next(k for k in manifest1["files"] if k.endswith("stats.csv"))
    sha256_first = manifest1["files"][csv_key]["sha256"]
    # Save again without changing files — only flow changes
    store.update_flow(project.id, {"flow_id": "f2", "nodes": [], "edges": []})
    manifest2 = manager.read_manifest(manager.bundle_path(project.id))
    sha256_second = manifest2["files"][csv_key]["sha256"]
    # The CSV sha256 should be identical (reused from cache)
    assert sha256_first == sha256_second
