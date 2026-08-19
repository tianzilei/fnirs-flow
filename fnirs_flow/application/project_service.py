"""Application-level project use cases with injected implementation ports."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class ProjectUseCasePort(Protocol):
    """Implementation port supplied by an interface composition root."""

    def validate(self, *args: Any, **kwargs: Any) -> Any: ...
    def compile(self, *args: Any, **kwargs: Any) -> Any: ...
    def discover(self, *args: Any, **kwargs: Any) -> Any: ...
    def dry_run(self, *args: Any, **kwargs: Any) -> Any: ...
    def execute(self, *args: Any, **kwargs: Any) -> Any: ...


class ProjectApplicationService:
    """Coordinate project use cases without depending on the HTTP package."""

    def __init__(self, store: Any, port: ProjectUseCasePort) -> None:
        self.store = store
        self.port = port

    def validate(self, project_id: str) -> Any:
        return self.port.validate(self.store, project_id)

    def compile(self, project_id: str, *, base_revision: int | None = None) -> Any:
        return self.port.compile(self.store, project_id, base_revision=base_revision)

    def discover(
        self,
        project_id: str,
        dataset_id: str,
        *,
        data_root: str | None = None,
        data_path: str | None = None,
        base_revision: int | None = None,
    ) -> Any:
        return self.port.discover(
            self.store,
            project_id,
            dataset_id,
            data_root=data_root,
            data_path=data_path,
            base_revision=base_revision,
        )

    def dry_run(self, project_id: str) -> Any:
        return self.port.dry_run(self.store, project_id)

    def execute(
        self,
        project_id: str,
        *,
        attempt_id: str = "",
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Any:
        return self.port.execute(
            self.store,
            project_id,
            attempt_id=attempt_id,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
