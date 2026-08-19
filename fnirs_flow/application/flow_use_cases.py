"""Flow validation and compilation use cases."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def validate_flow_payload(flow: dict[str, Any]) -> Any:
    """Validate a Flow payload independently of its interface adapter."""
    from fnirs_flow.validation.api import validate_flow

    return validate_flow(flow)


def compile_flow_payload(flow: dict[str, Any], outdir: str | Path) -> Any:
    """Compile a Flow payload independently of its interface adapter."""
    from fnirs_flow.compiler.compiler import compile_flow

    return compile_flow(flow, outdir)


class FlowUseCases:
    def __init__(self, *, validate: Callable[..., Any], compile: Callable[..., Any]) -> None:
        self._validate = validate
        self._compile = compile

    def validate(self, repository: Any, project_id: str) -> Any:
        return self._validate(repository, project_id)

    def compile(self, repository: Any, project_id: str, **kwargs: Any) -> Any:
        return self._compile(repository, project_id, **kwargs)
