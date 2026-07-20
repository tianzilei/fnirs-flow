#!/usr/bin/env python3
"""Benchmark real fnirs-flow project bundles.

Unlike the original smoke script, this benchmark writes its payload into the
managed project workspace and commits it to the canonical ``.fnirsflow`` file
before measuring list, open, save, and revision-storage costs.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fnirs_flow.api.project_bundle import ProjectBundleManager  # noqa: E402
from fnirs_flow.api.projects import ProjectStore  # noqa: E402

MIB = 1024 * 1024


def _timed(operation: Callable[[], Any], iterations: int) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - start) * 1000)
    return {
        "min_ms": min(samples),
        "max_ms": max(samples),
        "avg_ms": sum(samples) / len(samples),
    }


def _memory_gib() -> float | None:
    """Return physical memory without requiring an undeclared psutil dependency."""
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, ValueError):
        return None
    return pages * page_size / 1024**3


def _write_repeating_file(path: Path, size: int) -> None:
    block = b"subject,condition,value\nsub-01,left,0.123456\n" * 2048
    remaining = size
    with path.open("wb") as stream:
        while remaining:
            chunk = block[: min(len(block), remaining)]
            stream.write(chunk)
            remaining -= len(chunk)


def _write_random_file(path: Path, size: int) -> None:
    remaining = size
    with path.open("wb") as stream:
        while remaining:
            chunk_size = min(MIB, remaining)
            encoded = os.urandom((chunk_size // 2) + 1).hex().encode("ascii")[:chunk_size]
            stream.write(encoded)
            remaining -= len(encoded)


def populate_project_payload(
    output_dir: Path,
    size_mb: int,
    *,
    profile: str = "mixed",
) -> dict[str, Any]:
    """Write the requested payload into the canonical managed workspace."""
    if size_mb <= 0:
        raise ValueError("size_mb must be positive")
    if profile not in {"compressible", "incompressible", "mixed"}:
        raise ValueError(f"Unknown payload profile: {profile}")

    payload_dir = output_dir / "benchmark_payload"
    payload_dir.mkdir(parents=True, exist_ok=True)
    target_bytes = size_mb * MIB
    written = 0
    file_count = 0

    while written < target_bytes:
        size = min(MIB, target_bytes - written)
        use_random = profile == "incompressible" or (profile == "mixed" and file_count % 2 == 1)
        path = payload_dir / f"statistics_{file_count:05d}.csv"
        if use_random:
            _write_random_file(path, size)
        else:
            _write_repeating_file(path, size)
        written += size
        file_count += 1

    return {
        "requested_bytes": target_bytes,
        "written_bytes": written,
        "file_count": file_count,
        "profile": profile,
    }


def _bundle_payload_bytes(manager: ProjectBundleManager, project_id: str) -> int:
    manifest = manager.read_manifest(manager.bundle_path(project_id))
    return sum(int(details.get("size", 0)) for details in manifest.get("files", {}).values())


def _storage_usage(base_dir: Path, project_id: str) -> dict[str, Any]:
    current = base_dir / f"{project_id}.fnirsflow"
    version_dir = base_dir / ".versions" / project_id
    retained = sorted(version_dir.glob("*.fnirsflow")) if version_dir.exists() else []
    current_bytes = current.stat().st_size
    retained_bytes = sum(path.stat().st_size for path in retained)
    return {
        "current_bundle_bytes": current_bytes,
        "retained_bundle_count": len(retained),
        "retained_bundle_bytes": retained_bytes,
        "total_bundle_bytes": current_bytes + retained_bytes,
    }


def _measure_startup_and_list(base_dir: Path, iterations: int) -> dict[str, Any]:
    stores: list[ProjectStore] = []

    def startup() -> None:
        stores.append(ProjectStore(base_dir))

    startup_stats = _timed(startup, iterations)
    store = stores[-1]
    list_stats = _timed(store.list_all, iterations)
    return {
        "startup": startup_stats,
        "list_projects": {**list_stats, "project_count": len(store.list_all())},
    }


def _measure_open(base_dir: Path, project_id: str, iterations: int) -> dict[str, float]:
    store = ProjectStore(base_dir)
    return _timed(lambda: store.get(project_id), iterations)


def _measure_flow_saves(
    store: ProjectStore,
    project_id: str,
    iterations: int,
) -> dict[str, float]:
    counter = 0

    def save() -> None:
        nonlocal counter
        counter += 1
        flow = {
            "flow_id": "benchmark-flow",
            "nodes": [{"id": "n1", "revision_marker": counter}],
            "edges": [],
        }
        if not store.update_flow(project_id, flow):
            raise RuntimeError("Benchmark Flow save failed")

    return _timed(save, iterations)


def _ensure_revision_count(store: ProjectStore, project_id: str, revision_count: int) -> None:
    """Create enough Flow revisions to measure rolling-history amplification."""
    existing = len(store.get_version_history(project_id))
    for marker in range(existing, revision_count):
        flow = {
            "flow_id": "benchmark-history",
            "nodes": [{"id": "n1", "revision_marker": marker}],
            "edges": [],
        }
        if not store.update_flow(project_id, flow):
            raise RuntimeError("Benchmark revision save failed")


def benchmark_project_size(
    base_dir: Path,
    size_mb: int,
    *,
    profile: str,
    iterations: int,
    revision_count: int,
) -> dict[str, Any]:
    store = ProjectStore(base_dir)
    project = store.create(f"benchmark-{size_mb}mb", f"Real {size_mb} MiB benchmark")
    payload = populate_project_payload(store.get_output_dir(project.id), size_mb, profile=profile)

    commit_start = time.perf_counter()
    store.commit_project(project.id, reason="benchmark_payload_seeded")
    initial_commit_ms = (time.perf_counter() - commit_start) * 1000

    manager = ProjectBundleManager(base_dir)
    declared_payload_bytes = _bundle_payload_bytes(manager, project.id)
    if declared_payload_bytes < payload["written_bytes"]:
        raise RuntimeError(
            "Benchmark payload was not committed to the canonical project bundle "
            f"({declared_payload_bytes} < {payload['written_bytes']})"
        )

    lazy_metrics = _measure_startup_and_list(base_dir, iterations)
    open_metrics = _measure_open(base_dir, project.id, iterations)
    flow_save_metrics = _measure_flow_saves(store, project.id, iterations)
    _ensure_revision_count(store, project.id, revision_count)
    storage = _storage_usage(base_dir, project.id)

    return {
        "payload": {**payload, "declared_bundle_payload_bytes": declared_payload_bytes},
        "initial_commit_ms": initial_commit_ms,
        **lazy_metrics,
        "open_and_verify": open_metrics,
        "flow_only_save": flow_save_metrics,
        "storage": storage,
        "bundle_to_payload_ratio": storage["current_bundle_bytes"] / payload["written_bytes"],
        "history_space_amplification": storage["total_bundle_bytes"] / storage["current_bundle_bytes"],
    }


def run_benchmark(
    project_sizes: list[int],
    *,
    profile: str = "mixed",
    iterations: int = 3,
    revision_count: int = 10,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the benchmark using isolated real project stores."""
    if not project_sizes or any(size <= 0 for size in project_sizes):
        raise ValueError("project_sizes must contain positive MiB values")
    if any(size >= 10 for size in project_sizes):
        raise ValueError("project_sizes must stay below the 10 MiB container limit")
    if iterations <= 0 or revision_count <= 0:
        raise ValueError("iterations and revision_count must be positive")

    largest_size = max(project_sizes) * MIB
    required_free = largest_size * (revision_count + 2)
    free_bytes = shutil.disk_usage(work_dir or tempfile.gettempdir()).free
    if free_bytes < required_free:
        raise RuntimeError(
            f"Insufficient free space: need approximately {required_free / 1024**3:.1f} GiB"
        )

    results: dict[str, Any] = {
        "valid": True,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S%z"),
        "system": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "memory_gib": _memory_gib(),
        },
        "methodology": {
            "payload_location": "managed .workspaces/<project-id>/outputs/benchmark_payload",
            "canonical_bundle_verified": True,
            "profile": profile,
            "iterations": iterations,
            "target_revision_count": revision_count,
        },
        "benchmarks": {},
    }

    temp_parent = str(work_dir) if work_dir is not None else None
    for size_mb in project_sizes:
        with tempfile.TemporaryDirectory(prefix=f"fnirs-flow-{size_mb}mb-", dir=temp_parent) as temp_dir:
            base_dir = Path(temp_dir) / "store"
            results["benchmarks"][f"{size_mb}mb"] = benchmark_project_size(
                base_dir,
                size_mb,
                profile=profile,
                iterations=iterations,
                revision_count=revision_count,
            )
    return results


def benchmark_cold_start(
    base_dir: Path,
    project_count: int,
    *,
    size_mb: int = 1,
    iterations: int = 3,
) -> dict[str, Any]:
    """Create N projects and measure cold-start + list-all performance."""
    store = ProjectStore(base_dir)
    project_ids: list[str] = []
    create_times: list[float] = []
    for i in range(project_count):
        start = time.perf_counter()
        project = store.create(f"cold-{i}", f"Cold start project {i}")
        create_times.append((time.perf_counter() - start) * 1000)
        # Seed a small payload
        payload_dir = store.get_output_dir(project.id) / "benchmark_payload"
        payload_dir.mkdir(parents=True, exist_ok=True)
        _write_repeating_file(payload_dir / "data.csv", size_mb * MIB)
        store.commit_project(project.id, reason="cold_start_seed")
        project_ids.append(project.id)

    # Measure cold startup (new store instance on existing directory)
    def cold_startup() -> ProjectStore:
        return ProjectStore(base_dir)

    startup_stats = _timed(cold_startup, iterations)
    cold_store = cold_startup()
    list_stats = _timed(cold_store.list_all, iterations)
    open_stats = _timed(lambda: cold_store.get(project_ids[0]), iterations)

    return {
        "project_count": project_count,
        "size_mb_per_project": size_mb,
        "create_avg_ms": sum(create_times) / len(create_times) if create_times else 0,
        "startup": startup_stats,
        "list_projects": {**list_stats, "project_count": len(cold_store.list_all())},
        "open_first_project": open_stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark real fnirs-flow project bundles")
    parser.add_argument("--sizes", nargs="+", type=int, default=[1, 4, 8], metavar="MIB")
    parser.add_argument(
        "--profile",
        choices=["compressible", "incompressible", "mixed"],
        default="mixed",
    )
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--revisions", type=int, default=10)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("benchmark_results.json"))
    parser.add_argument("--cold-start", type=int, default=0, metavar="N",
                        help="Run cold start benchmark with N projects (0 to skip)")
    parser.add_argument("--cold-start-size", type=int, default=1, metavar="MIB",
                        help="MiB per project for cold start benchmark")
    args = parser.parse_args()

    results = run_benchmark(
        args.sizes,
        profile=args.profile,
        iterations=args.iterations,
        revision_count=args.revisions,
        work_dir=args.work_dir,
    )

    if args.cold_start > 0:
        temp_parent = str(args.work_dir) if args.work_dir is not None else None
        with tempfile.TemporaryDirectory(prefix="fnirs-flow-cold-", dir=temp_parent) as temp_dir:
            base_dir = Path(temp_dir) / "store"
            results["cold_start"] = benchmark_cold_start(
                base_dir,
                args.cold_start,
                size_mb=args.cold_start_size,
                iterations=args.iterations,
            )

    args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Benchmark results written to {args.output}")


if __name__ == "__main__":
    main()
