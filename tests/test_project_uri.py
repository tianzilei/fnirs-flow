"""Regression tests for portable project and external-data URIs."""

from __future__ import annotations

from pathlib import Path

import pytest

from fnirs_flow.api.uri import (
    ProjectURI,
    URIBindingStore,
    create_external_data_uri,
    create_project_uri,
    path_to_external_data_uri,
    path_to_project_uri,
    resolve_external_data_uri,
    resolve_project_uri,
)


def test_project_uri_round_trip(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    artifact = project_dir / "outputs" / "roi" / "result.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("value\n1\n", encoding="utf-8")

    uri = create_project_uri("outputs/roi/result.csv")

    assert uri.uri == "project://outputs/roi/result.csv"
    assert uri.path.as_posix() == "outputs/roi/result.csv"
    assert resolve_project_uri(uri, project_dir) == artifact.resolve()
    assert path_to_project_uri(artifact, project_dir) == uri


def test_external_data_uri_round_trip(tmp_path: Path) -> None:
    data_root = tmp_path / "dataset"
    snirf = data_root / "sub-01" / "run.snirf"
    snirf.parent.mkdir(parents=True)
    snirf.write_bytes(b"fixture")

    uri = create_external_data_uri("ds007738", "sub-01/run.snirf")

    assert uri.uri == "external-data://ds007738/sub-01/run.snirf"
    assert uri.dataset_id == "ds007738"
    assert uri.path.as_posix() == "sub-01/run.snirf"
    assert resolve_external_data_uri(uri, {"ds007738": data_root}) == snirf.resolve()
    assert path_to_external_data_uri(snirf, {"ds007738": data_root}) == uri


@pytest.mark.parametrize(
    "value",
    [
        "../outside.txt",
        "outputs/../../outside.txt",
        "/absolute/path.txt",
        r"C:\absolute\path.txt",
        "outputs//result.csv",
        "outputs/./result.csv",
    ],
)
def test_project_uri_rejects_unsafe_paths(value: str) -> None:
    with pytest.raises(ValueError):
        create_project_uri(value)


@pytest.mark.parametrize(
    "uri",
    [
        "project:///outputs/result.csv",
        "project://outputs/../secret.txt",
        "project://outputs/result.csv?raw=1",
        "project://outputs/result.csv#section",
        "https://example.test/result.csv",
        "external-data://../secret.snirf",
    ],
)
def test_parser_rejects_noncanonical_or_unsafe_uris(uri: str) -> None:
    with pytest.raises(ValueError):
        ProjectURI(uri)


def test_uri_resolution_does_not_escape_through_symlink(tmp_path: Path) -> None:
    import sys

    if sys.platform == "win32":
        import pytest

        pytest.skip("Symlink creation requires elevated privileges on Windows")
    project_dir = tmp_path / "project"
    outside = tmp_path / "outside"
    project_dir.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (project_dir / "linked").symlink_to(outside, target_is_directory=True)

    assert resolve_project_uri(create_project_uri("linked/secret.txt"), project_dir) is None


def test_binding_store_persists_and_resolves(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    data_root = tmp_path / "dataset"
    source = data_root / "sub-01" / "run.snirf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fixture")

    store = URIBindingStore(state_dir)
    store.bind("ds007738", data_root)

    reloaded = URIBindingStore(state_dir)
    uri = create_external_data_uri("ds007738", "sub-01/run.snirf")
    assert reloaded.get_binding("ds007738") == data_root.resolve()
    assert reloaded.resolve_uri(uri) == source.resolve()


def test_path_conversion_rejects_files_outside_roots(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    data_dir = tmp_path / "data"
    outside = tmp_path / "outside.txt"
    project_dir.mkdir()
    data_dir.mkdir()
    outside.write_text("outside", encoding="utf-8")

    assert path_to_project_uri(outside, project_dir) is None
    assert path_to_external_data_uri(outside, {"dataset": data_dir}) is None
