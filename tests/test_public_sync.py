"""Tests for the public release synchronization policy."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_sync_module():
    path = Path(__file__).parents[1] / "scripts" / "sync_public_release.py"
    spec = importlib.util.spec_from_file_location("sync_public_release", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_english_gate_accepts_english_text(tmp_path):
    module = _load_sync_module()
    source = tmp_path / "README.md"
    source.write_text("English public documentation.\n", encoding="utf-8")

    module.validate_english_public_text([module.CopyItem(source, tmp_path / "target.md")])


def test_english_gate_reports_chinese_text_line(tmp_path):
    module = _load_sync_module()
    source = tmp_path / "README.md"
    chinese_line = "\u4e2d\u6587\u53d1\u5e03\u6587\u672c\u3002"
    source.write_text(f"English line.\n{chinese_line}\n", encoding="utf-8")

    with pytest.raises(SystemExit, match=r"README\.md:2"):
        module.validate_english_public_text([module.CopyItem(source, tmp_path / "target.md")])
