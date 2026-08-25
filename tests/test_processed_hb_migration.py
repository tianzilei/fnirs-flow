from __future__ import annotations

import pytest

from fnirs_flow.flow.migration import migrate_flow_schema_v0_3_to_v0_4


def test_ar1_migration_requires_explicit_confirmation():
    flow = {
        "schema_version": "0.3.0",
        "flow_id": "legacy",
        "flow_atoms": [{"config": {"noise_model": "ar1"}}],
        "edges": [],
    }
    with pytest.raises(ValueError, match="AR1_SEMANTIC_CHANGE_CONFIRMATION_REQUIRED"):
        migrate_flow_schema_v0_3_to_v0_4(flow)
    migrated, audit = migrate_flow_schema_v0_3_to_v0_4(flow, confirm_ar1_semantic_change=True)
    assert migrated["schema_version"] == "0.4.0"
    assert migrated["solver"]["requested"] == "ar1"
    assert "solver_requested_ar1" in audit["actions"]
