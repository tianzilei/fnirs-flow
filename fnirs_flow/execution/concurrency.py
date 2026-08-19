"""Validated effective concurrency and native-thread budgets."""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any

from fnirs_flow.settings import Settings


@dataclass(frozen=True)
class EffectiveConcurrency:
    requested_backend: str
    backend: str
    job_workers: int
    requested_run_workers: int
    run_workers: int
    blas_threads: int
    memory_budget_mb: int | None
    available_memory_mb: int | None
    logical_cpu_count: int
    physical_cpu_count: int | None
    native_threadpools: list[dict[str, Any]]
    fallback_reason: str = ""
    warning: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _physical_cpu_count() -> int | None:
    try:
        import psutil  # type: ignore[import-untyped]

        count = psutil.cpu_count(logical=False)
        return int(count) if count is not None else None
    except ImportError:
        return None


def _available_memory_mb() -> int | None:
    try:
        import psutil  # type: ignore[import-untyped]

        return int(psutil.virtual_memory().available / 1024**2)
    except ImportError:
        return None


def _native_threadpools() -> list[dict[str, Any]]:
    try:
        from threadpoolctl import threadpool_info  # type: ignore[import-untyped]
    except ImportError:
        return []
    return [
        {
            "internal_api": str(item.get("internal_api", "")),
            "num_threads": int(item.get("num_threads", 0) or 0),
            "prefix": str(item.get("prefix", "")),
            "version": str(item.get("version", "")),
        }
        for item in threadpool_info()
    ]


def resolve_concurrency(settings: Settings, *, run_count: int) -> EffectiveConcurrency:
    logical = max(1, os.cpu_count() or 1)
    physical = _physical_cpu_count()
    available_memory = _available_memory_mb()
    blas_threads = settings.blas_threads or 1
    requested_workers = settings.run_workers
    run_workers = requested_workers
    backend = settings.parallel_backend
    fallback_reason = ""

    if backend == "process" and run_count < 2:
        backend, run_workers, fallback_reason = "serial", 1, "fewer_than_two_runs"
    elif backend == "serial" or requested_workers == 1:
        backend, run_workers = "serial", 1
        if settings.parallel_backend == "process":
            fallback_reason = "single_worker_requested"

    budget_cpu = settings.job_workers * run_workers * blas_threads
    warning = ""
    if budget_cpu > logical:
        safe_workers = max(1, logical // max(1, settings.job_workers * blas_threads))
        if backend == "process" and safe_workers < run_workers:
            run_workers = safe_workers
            if run_workers == 1:
                backend = "serial"
                fallback_reason = "cpu_budget"
        warning = (
            "Requested job_workers * run_workers * blas_threads exceeds logical CPUs; "
            f"effective run_workers reduced to {run_workers}."
        )
        warnings.warn(warning, RuntimeWarning, stacklevel=2)

    if settings.memory_budget_mb is not None and available_memory is not None:
        usable = min(settings.memory_budget_mb, available_memory)
        # Conservative admission rule: reserve 256 MiB for each scientific worker.
        memory_workers = max(1, usable // 256)
        if backend == "process" and memory_workers < run_workers:
            run_workers = memory_workers
            if run_workers == 1:
                backend = "serial"
                fallback_reason = "memory_budget"

    return EffectiveConcurrency(
        requested_backend=settings.parallel_backend,
        backend=backend,
        job_workers=settings.job_workers,
        requested_run_workers=requested_workers,
        run_workers=run_workers,
        blas_threads=blas_threads,
        memory_budget_mb=settings.memory_budget_mb,
        available_memory_mb=available_memory,
        logical_cpu_count=logical,
        physical_cpu_count=physical,
        native_threadpools=_native_threadpools(),
        fallback_reason=fallback_reason,
        warning=warning,
    )


@contextmanager
def native_thread_limit(limit: int) -> Iterator[None]:
    """Apply a runtime BLAS/OpenMP limit when threadpoolctl is available."""
    try:
        from threadpoolctl import threadpool_limits  # type: ignore[import-untyped]
    except ImportError:
        yield
        return
    with threadpool_limits(limits=limit):
        yield
