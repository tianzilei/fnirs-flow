"""Package export use case."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class PackageUseCases:
    def __init__(self, *, export: Callable[..., Any]) -> None:
        self._export = export

    def export(self, repository: Any, project_id: str, **kwargs: Any) -> Any:
        return self._export(repository, project_id, **kwargs)
