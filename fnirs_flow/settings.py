"""Immutable process settings read once by composition roots."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class SettingsValidationError(ValueError):
    """Raised when an environment-backed runtime setting is invalid."""


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsValidationError(f"{name} must be an integer, got {raw!r}") from exc
    if value < 1:
        raise SettingsValidationError(f"{name} must be >= 1, got {value}")
    return value


def _optional_positive_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsValidationError(f"{name} must be an integer, got {raw!r}") from exc
    if value < 1:
        raise SettingsValidationError(f"{name} must be >= 1, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    project_store_dir: Path = Path("outputs/api_projects")
    allowed_path_roots: tuple[Path, ...] = ()
    api_key: str = ""
    cors_origins: tuple[str, ...] = ()
    webui_resource_package: str = "fnirs_flow.resources.webui"
    webui_resource_path: str = "dist"
    registry_cache_dir: Path = Path("outputs/api_projects/.cache/registry")
    job_workers: int = 2
    run_workers: int = 1
    blas_threads: int | None = None
    parallel_backend: Literal["serial", "process"] = "serial"
    memory_budget_mb: int | None = None
    progress_buffer_limit: int = 1000
    bundle_retention: int = 5

    @classmethod
    def from_env(cls) -> Settings:
        project_store_dir = Path(os.environ.get("FNIRS_PROJECT_STORE_DIR", "outputs/api_projects"))
        roots = tuple(
            Path(value).expanduser().resolve()
            for value in os.environ.get("FNIRS_ALLOWED_PATH_ROOTS", "").split(os.pathsep)
            if value.strip()
        )
        cors = tuple(value.strip() for value in os.environ.get("FNIRS_CORS_ORIGINS", "").split(",") if value.strip())
        backend = os.environ.get("FNIRS_PARALLEL_BACKEND", "serial").strip().lower()
        if backend not in {"serial", "process"}:
            raise SettingsValidationError(
                f"FNIRS_PARALLEL_BACKEND must be 'serial' or 'process', got {backend!r}"
            )
        return cls(
            project_store_dir=project_store_dir,
            allowed_path_roots=roots,
            api_key=os.environ.get("FNIRS_API_KEY", ""),
            cors_origins=cors,
            webui_resource_package=os.environ.get(
                "FNIRS_WEBUI_RESOURCE_PACKAGE", "fnirs_flow.resources.webui"
            ),
            webui_resource_path=os.environ.get("FNIRS_WEBUI_RESOURCE_PATH", "dist"),
            registry_cache_dir=Path(
                os.environ.get(
                    "FNIRS_REGISTRY_CACHE_DIR",
                    str(project_store_dir / ".cache" / "registry"),
                )
            ),
            job_workers=_positive_int("FNIRS_JOB_WORKERS", 2),
            run_workers=_positive_int("FNIRS_RUN_WORKERS", 1),
            blas_threads=_optional_positive_int("FNIRS_BLAS_THREADS"),
            parallel_backend=backend,  # type: ignore[arg-type]
            memory_budget_mb=_optional_positive_int("FNIRS_MEMORY_BUDGET_MB"),
            progress_buffer_limit=_positive_int("FNIRS_PROGRESS_BUFFER_LIMIT", 1000),
            bundle_retention=_positive_int("FNIRS_BUNDLE_RETENTION", 5),
        )


settings = Settings.from_env()
