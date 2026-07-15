"""Tests for filesystem metadata filtering helpers."""

from __future__ import annotations

from fnirs_flow.filesystem import (
    is_macos_metadata_path,
    macos_metadata_ignore,
    remove_macos_metadata_paths,
)


def test_detects_macos_metadata_paths() -> None:
    assert is_macos_metadata_path("._flow.json")
    assert is_macos_metadata_path("outputs/.DS_Store")
    assert is_macos_metadata_path("__MACOSX/project.json")
    assert is_macos_metadata_path("nested/.AppleDouble/file")


def test_allows_regular_data_paths() -> None:
    assert not is_macos_metadata_path("outputs/compiled/flow.json")
    assert not is_macos_metadata_path("sub-01/nirs/sub-01_task-tapping_nirs.snirf")


def test_remove_macos_metadata_paths(tmp_path) -> None:
    real_file = tmp_path / "outputs" / "compiled" / "flow.json"
    real_file.parent.mkdir(parents=True)
    real_file.write_text("{}", encoding="utf-8")
    sidecar = real_file.with_name(f"._{real_file.name}")
    sidecar.write_bytes(b"appledouble")
    macosx = tmp_path / "__MACOSX"
    macosx.mkdir()
    (macosx / "flow.json").write_text("{}", encoding="utf-8")

    removed = remove_macos_metadata_paths(tmp_path)

    assert real_file.exists()
    assert not sidecar.exists()
    assert not macosx.exists()
    assert {path.name for path in removed} >= {"._flow.json", "__MACOSX"}


def test_macos_metadata_ignore_for_copytree() -> None:
    names = ["flow.json", "._flow.json", ".DS_Store", "__MACOSX", ".AppleDouble"]

    assert macos_metadata_ignore("/tmp/project", names) == [
        "._flow.json",
        ".DS_Store",
        "__MACOSX",
        ".AppleDouble",
    ]
