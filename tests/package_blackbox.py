"""Installed-wheel black-box checks; run from a directory outside the source tree."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from fnirs_flow.api.app import app
from fnirs_flow.flow.schemas import validate_flow_dict
from fnirs_flow.registry.methodatom_library import load_literature_method_atom_templates


def main() -> None:
    valid = {"schema_version": "0.3.0", "flow_id": "wheel", "flow_atoms": [], "edges": []}
    invalid = {"schema_version": "0.3.0", "flow_id": "invalid"}
    assert validate_flow_dict(valid) == []
    assert validate_flow_dict(invalid)
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    root = client.get("/")
    assert root.status_code == 200
    match = re.search(r'(?:src|href)="(/assets/[^"]+)', root.text)
    assert match and client.get(match.group(1)).status_code == 200
    assert load_literature_method_atom_templates()


if __name__ == "__main__":
    main()
