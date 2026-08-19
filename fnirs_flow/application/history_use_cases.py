"""History query use case."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class HistoryUseCases:
    def __init__(self, *, list_history: Callable[..., Any]) -> None:
        self._list_history = list_history

    def list(self, repository: Any, project_id: str) -> Any:
        return self._list_history(repository, project_id)
