"""Contracts for immutable resources used by source and wheel installs."""

from __future__ import annotations

import json
from importlib.resources import files

from fnirs_flow.registry.methodatom_library import load_literature_method_atom_templates


def test_packaged_schema_is_authoritative() -> None:
    schema = files("fnirs_flow.resources.schemas").joinpath("fnirs_flow.schema.json")
    assert schema.is_file()
    document = json.loads(schema.read_text(encoding="utf-8"))
    assert document["properties"]["schema_version"]["enum"] == ["0.1.0", "0.2.0", "0.3.0"]


def test_packaged_webui_has_entrypoint_and_asset() -> None:
    dist = files("fnirs_flow.resources.webui").joinpath("dist")
    index = dist.joinpath("index.html")
    assert index.is_file()
    assert any(item.name.endswith((".js", ".css")) for item in dist.joinpath("assets").iterdir())


def test_packaged_methodatom_library_loads() -> None:
    assert load_literature_method_atom_templates()
