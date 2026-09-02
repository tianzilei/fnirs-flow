"""Tests for the public release synchronization policy."""

from __future__ import annotations

import importlib.util
import os
import subprocess
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


def test_generic_naming_gate_accepts_domain_neutral_text(tmp_path):
    module = _load_sync_module()
    source = tmp_path / "processed_hb.md"
    source.write_text("Generic vendor-processed haemoglobin analysis.\n", encoding="utf-8")

    module.validate_generic_public_naming([module.CopyItem(source, tmp_path / "target.md")])


def test_generic_naming_gate_reports_specific_text_line(tmp_path):
    module = _load_sync_module()
    source = tmp_path / "README.md"
    prohibited = "acu" + "puncture"
    source.write_text(f"Generic line.\nSpecific {prohibited} workflow.\n", encoding="utf-8")

    with pytest.raises(SystemExit, match=r"README\.md:2"):
        module.validate_generic_public_naming([module.CopyItem(source, tmp_path / "target.md")])


def test_generic_naming_gate_reports_specific_filename(tmp_path):
    module = _load_sync_module()
    prohibited = "acu" + "puncture"
    source = tmp_path / f"{prohibited}_flow.json"
    source.write_text("{}\n", encoding="utf-8")

    with pytest.raises(SystemExit, match=r"path; policy term"):
        module.validate_generic_public_naming([module.CopyItem(source, tmp_path / "target.json")])


def test_public_ci_tools_are_in_copy_plan(tmp_path):
    module = _load_sync_module()
    root = Path(__file__).parents[1]
    plan = module.build_copy_plan(root, tmp_path)
    copied = {item.source.relative_to(root).as_posix() for item in plan}

    assert set(module.PUBLIC_TOOL_FILES) <= copied
    assert not any(any(part.startswith("._") for part in Path(path).parts) for path in copied)
    assert any(path.startswith("fnirs_flow/resources/webui/dist/") for path in copied)
    assert "docs/processed_hb_analysis.md" not in copied
    assert any(path.startswith("fnirs_flow/processed_hb/") for path in copied)
    assert "fnirs_flow/processed_hb/modeling.py" not in copied
    assert "fnirs_flow/processed_hb/pipeline.py" not in copied
    assert "schemas/processed_hb_analysis.schema.json" not in copied
    assert "tests/test_processed_hb.py" not in copied
    assert "tests/test_processed_hb_cli.py" not in copied
    assert "tests/test_calibration_holdout_validation.py" not in copied
    assert "tests/test_evidence_count_report.py" not in copied
    assert "tests/test_evidence_inventory.py" not in copied
    assert "tests/test_v130_readiness.py" not in copied
    assert "tests/test_release_governance.py" not in copied


def test_public_tree_includes_only_generic_processed_hb_modules(tmp_path):
    module = _load_sync_module()
    root = Path(__file__).parents[1]
    target = tmp_path / "public"
    plan = module.build_copy_plan(root, target)
    module.copy_items(plan, dry_run=False)

    split_test = (target / "tests" / "test_processed_hb_split.py").read_text(encoding="utf-8")
    assert "fnirs_flow.processed_hb" not in split_test
    assert "Sample/" not in split_test
    assert (target / "fnirs_flow" / "processed_hb" / "windows.py").is_file()
    assert not (target / "fnirs_flow" / "processed_hb" / "pipeline.py").exists()
    assert not (target / "fnirs_flow" / "processed_hb" / "modeling.py").exists()
    assert not (target / "docs" / "processed_hb_analysis.md").exists()

    environment = dict(os.environ)
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(target), existing_pythonpath) if part
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import fnirs_flow.adapters; import fnirs_flow.cli; import fnirs_flow.processed_hb",
        ],
        cwd=target,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    help_result = subprocess.run(
        [sys.executable, "-m", "fnirs_flow.cli", "--help"],
        cwd=target,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "run-processed-hb" not in help_result.stdout


def test_unexpected_target_file_is_rejected(tmp_path):
    module = _load_sync_module()
    source = tmp_path / "source.md"
    target = tmp_path / "public"
    target.mkdir()
    source.write_text("public\n", encoding="utf-8")
    (target / "source.md").write_text("public\n", encoding="utf-8")
    (target / "cache.pyc").write_bytes(b"cache")

    plan = [module.CopyItem(source, target / "source.md")]
    with pytest.raises(SystemExit, match=r"cache\.pyc"):
        module.audit_unexpected_target_files(target, plan, dry_run=False)


def test_manifest_uses_public_project_name(tmp_path):
    module = _load_sync_module()
    source_root = tmp_path / "private-checkout-name"
    target_root = tmp_path / "public-checkout-name"
    source_root.mkdir()
    source = source_root / "README.md"
    source.write_text("public\n", encoding="utf-8")

    manifest = module.build_manifest(
        source_root,
        target_root,
        [module.CopyItem(source, target_root / "README.md")],
    )

    assert manifest["source_root_name"] == "fnirs-flow"
    assert manifest["target_root_name"] == "fnirs-flow"
