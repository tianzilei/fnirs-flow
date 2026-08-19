"""Composition adapter connecting API project functions to application ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fnirs_flow.application.project_use_cases import (
    compile_project_flow,
    discover_project_data,
    dry_run_project,
    execute_project_runs,
    validate_project_flow,
)


@dataclass
class APIProjectUseCases:
    validate: Any = validate_project_flow
    compile: Any = compile_project_flow
    discover: Any = discover_project_data
    dry_run: Any = dry_run_project
    execute: Any = execute_project_runs
