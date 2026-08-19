"""Executable governance checks for generated contracts and release boundaries."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_script_classification_is_complete() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/audit/check_script_classification.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_generated_api_responses_are_not_redeclared_as_client_interfaces() -> None:
    generated = (ROOT / "webui/src/api/generated.ts").read_text(encoding="utf-8")
    client = (ROOT / "webui/src/api/client.ts").read_text(encoding="utf-8")
    generated_names = set(re.findall(r"^export interface (\w+)", generated, re.MULTILINE))
    client_names = set(re.findall(r"^export interface (\w+)", client, re.MULTILINE))
    duplicated = sorted(generated_names & client_names)
    assert not duplicated, f"API DTOs must alias generated contracts, not duplicate interfaces: {duplicated}"
