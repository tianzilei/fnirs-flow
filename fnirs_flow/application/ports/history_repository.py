"""Design-history persistence port."""

from __future__ import annotations

from typing import Any, Protocol


class HistoryRepository(Protocol):
    def list_history(self, project_id: str) -> list[dict[str, Any]]: ...
