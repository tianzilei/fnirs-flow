"""Tests for MethodAtom-first model aliases and FlowGraph atom accessors."""

from fnirs_flow.flow.atoms import (
    ReadinessStatus,
)
from fnirs_flow.flow.models import (
    AtomPort,
    FlowAtom,
    FlowAtomStateContract,
    FlowGraph,
    FlowNode,
    MethodAtomCategory,
    MethodAtomOrigin,
    NodeCategory,
    NodeOrigin,
    NodePort,
    NodeStateContract,
    NodeStatus,
)


class TestMethodAtomAliases:
    """Verify that MethodAtom-first aliases resolve to the same types."""

    def test_flow_atom_is_flow_node(self):
        assert FlowAtom is FlowNode

    def test_atom_port_is_node_port(self):
        assert AtomPort is NodePort

    def test_method_atom_category_is_node_category(self):
        assert MethodAtomCategory is NodeCategory

    def test_readiness_status_maps_to_node_status_values(self):
        """ReadinessStatus is a new split enum; NodeStatus is the legacy combined enum.
        They share some values but are no longer the same type."""
        # Verify ReadinessStatus has the expected values
        assert ReadinessStatus.NOT_CONFIGURED.value == "not_configured"
        assert ReadinessStatus.READY.value == "ready"
        assert ReadinessStatus.BLOCKED.value == "blocked"
        # Verify NodeStatus still exists for backward compatibility
        assert NodeStatus.NOT_CONFIGURED.value == "not_configured"
        assert NodeStatus.READY.value == "ready"

    def test_method_atom_origin_is_node_origin(self):
        assert MethodAtomOrigin is NodeOrigin

    def test_flow_atom_state_contract_is_node_state_contract(self):
        assert FlowAtomStateContract is NodeStateContract

    def test_create_flow_atom_with_new_name(self):
        atom = FlowAtom(
            id="test-atom",
            type="optical_density",
            category=MethodAtomCategory.PREPROCESSING,
        )
        assert atom.id == "test-atom"
        assert atom.category == MethodAtomCategory.PREPROCESSING

    def test_non_user_config_fields_are_normalized(self):
        atom = FlowAtom.model_validate(
            {
                "id": "legacy-atom",
                "type": "dataset_discovery",
                "category": "data",
                "config": {
                    "dataset_id": "demo",
                    "source_kind": "mne_nirs_dataset",
                    "readiness_status": "ready",
                    "execution_scope": "group",
                    "source_atom_id": "ATOM_demo",
                },
            }
        )
        assert atom.config == {"dataset_id": "demo"}
        assert atom.readiness_status == ReadinessStatus.READY
        assert atom.execution_scope == "group"
        assert atom.metadata["source_atom_id"] == "ATOM_demo"

    def test_create_atom_port_with_new_name(self):
        port = AtomPort(
            name="raw_data",
            direction="in",
            schema="RawData",
        )
        assert port.name == "raw_data"
        assert port.direction == "in"


class TestFlowGraphAtomAccessors:
    """Test FlowGraph's MethodAtom-first accessors."""

    def _make_flow(self) -> FlowGraph:
        return FlowGraph(
            flow_id="test-flow",
            nodes=[
                FlowNode(id="n1", type="optical_density", category="preprocessing"),
                FlowNode(id="n2", type="beer_lambert_law", category="preprocessing"),
            ],
        )

    def test_atom_map_from_nodes(self):
        flow = self._make_flow()
        atoms = flow.atom_map()
        assert len(atoms) == 2
        assert "n1" in atoms
        assert "n2" in atoms

    def test_get_atom_from_nodes(self):
        flow = self._make_flow()
        atom = flow.get_atom("n1")
        assert atom is not None
        assert atom.type == "optical_density"

    def test_get_atom_missing(self):
        flow = self._make_flow()
        assert flow.get_atom("nonexistent") is None

    def test_atom_map_prefers_flow_atoms(self):
        flow = FlowGraph(
            flow_id="test-flow",
            nodes=[
                FlowNode(id="n1", type="optical_density", category="preprocessing"),
            ],
            flow_atoms=[
                FlowNode(id="n1", type="optical_density", category="preprocessing"),
                FlowNode(id="n2", type="beer_lambert_law", category="preprocessing"),
            ],
        )
        atoms = flow.atom_map()
        assert len(atoms) == 2
        assert "n2" in atoms

    def test_flow_atoms_only_populates_nodes(self):
        flow = FlowGraph.model_validate(
            {
                "schema_version": "0.2.0",
                "flow_id": "atoms-only",
                "flow_atoms": [
                    {
                        "id": "a1",
                        "atom_type": "optical_density",
                        "category": "preprocessing",
                        "position": {"x": 0, "y": 0},
                        "status": "configured",
                    },
                ],
                "edges": [],
            }
        )
        assert len(flow.nodes) == 1
        assert flow.nodes[0].type == "optical_density"
        assert flow.nodes[0].atom_type == "optical_density"
        assert flow.atom_map()["a1"].type == "optical_density"


class TestFlowGraphDualWrite:
    """Test FlowGraph flow_atoms dual-write field."""

    def test_flow_atoms_default_none(self):
        flow = FlowGraph(flow_id="test")
        assert flow.flow_atoms is None

    def test_flow_atoms_populated(self):
        flow = FlowGraph(
            flow_id="test",
            nodes=[
                FlowNode(id="n1", type="optical_density", category="preprocessing"),
            ],
            flow_atoms=[
                FlowNode(id="n1", type="optical_density", category="preprocessing"),
            ],
        )
        assert flow.flow_atoms is not None
        assert len(flow.flow_atoms) == 1
