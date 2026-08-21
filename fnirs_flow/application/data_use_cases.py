"""Data discovery and metadata use cases."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def discover_dataset_to_workspace(
    dataset_id: str,
    outdir: str | Path,
    *,
    data_root: str | Path | None = None,
) -> Any:
    """Discover dataset metadata independently of an interface adapter."""
    from fnirs_flow.data.discovery import discover_dataset

    return discover_dataset(dataset_id, outdir, local_root=data_root)


class DataUseCases:
    def __init__(self, *, discover: Callable[..., Any]) -> None:
        self._discover = discover

    def discover(self, repository: Any, project_id: str, dataset_id: str, **kwargs: Any) -> Any:
        return self._discover(repository, project_id, dataset_id, **kwargs)
