from fnirs_flow.flow.schemas import validate_flow_dict


def test_processed_hb_rejects_raw_intensity_operations():
    flow = {
        "schema_version": "0.4.0",
        "flow_id": "x",
        "data_semantics": {
            "branch": "vendor_processed_hb",
            "signal_level": "haemoglobin_vendor_processed",
            "absolute_unit_verified": False,
        },
        "solver": {"requested": "ar1", "fallback_policy": "forbid", "confirmatory": True},
        "flow_atoms": [
            {
                "id": "od",
                "atom_type": "optical_density",
                "operation": "optical_density",
                "category": "preprocessing",
                "position": {"x": 0, "y": 0},
            }
        ],
        "edges": [],
    }
    assert any("cannot use raw-intensity" in error for error in validate_flow_dict(flow))


def test_confirmatory_processed_hb_rejects_unfrozen_contract():
    flow = {
        "schema_version": "0.4.0",
        "flow_id": "x",
        "edges": [],
        "data_semantics": {
            "branch": "vendor_processed_hb",
            "signal_level": "haemoglobin_vendor_processed",
            "absolute_unit_verified": False,
        },
        "solver": {"requested": "ar1_irls", "fallback_policy": "forbid", "confirmatory": True},
        "processed_hb": {"scientific_parameters_frozen": False},
        "flow_atoms": [
            {
                "id": operation,
                "atom_type": operation,
                "operation": operation,
                "category": "analysis",
                "position": {"x": 0, "y": 0},
            }
            for operation in (
                "frozen_manifest_discovery",
                "read_vendor_processed_hb",
                "ingest_frozen_events",
                "regularize_processed_hb_time",
                "compile_processed_hb_designs",
                "fit_processed_hb_first_level",
                "estimate_full_contrasts",
                "write_processed_hb_derivatives",
            )
        ],
    }
    errors = validate_flow_dict(flow)
    assert any("scientific_parameters_frozen=true" in error for error in errors)
    assert any("requires a non-empty covariance contract" in error for error in errors)
