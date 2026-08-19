from fnirs_flow.flow.serialization import load_canonical_flow, normalize_flow_payload, serialize_flow_payload


def test_legacy_flow_normalizes_to_canonical_fields():
    flow = load_canonical_flow({"schema_version": "0.1.0", "flow_id": "legacy", "nodes": [], "edges": []})
    payload = serialize_flow_payload(flow, schema_version="0.3.0")
    assert "flow_atoms" in payload
    assert "nodes" not in payload


def test_legacy_atom_type_is_converted_at_boundary():
    payload = normalize_flow_payload(
        {
            "schema_version": "0.1.0",
            "flow_id": "legacy",
            "nodes": [
                {
                    "id": "n",
                    "type": "read_run",
                    "category": "data",
                    "position": {"x": 0, "y": 0},
                }
            ],
            "edges": [],
        }
    )
    assert payload["flow_atoms"][0]["atom_type"] == "read_run"
    assert "type" not in payload["flow_atoms"][0]
