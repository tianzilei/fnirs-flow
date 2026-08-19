"""Execution port shared by CLI and HTTP interfaces."""

from __future__ import annotations

from typing import Any, Protocol


class ExecutionGateway(Protocol):
    def execute(self, request: Any) -> Any: ...
