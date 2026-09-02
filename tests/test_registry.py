"""Tests for registry: evidence store, methods, risk rules, presets, node library."""

from __future__ import annotations

import csv

import pytest

from fnirs_flow.registry.evidence_store import EvidenceItem, EvidenceRecord, EvidenceStore
from fnirs_flow.registry.methods import BUILTIN_METHODS, MethodLibrary
from fnirs_flow.registry.node_library import NodeLibrary
from fnirs_flow.registry.node_templates import ALL_NODE_TEMPLATES
from fnirs_flow.registry.presets import BUILTIN_PRESETS, PresetLibrary
from fnirs_flow.registry.risk_rules import BUILTIN_RISK_RULES, RiskRuleLibrary


class TestEvidenceStore:
    def test_add_and_retrieve(self):
        store = EvidenceStore()
        rec = EvidenceRecord(
            record_id="r1",
            paper_title="Test Paper",
            method_domain="preprocessing",
            items=[EvidenceItem(item_id="i1", field="method", value="TDDR", confidence="direct")],
        )
        with pytest.raises(RuntimeError, match="read-only"):
            store.add(rec)
        assert store.all() == []

    def test_direct_items(self):
        store = EvidenceStore()
        rec = EvidenceRecord(
            record_id="r1",
            items=[
                EvidenceItem(item_id="i1", confidence="direct"),
                EvidenceItem(item_id="i2", confidence="conditional"),
            ],
        )
        with pytest.raises(RuntimeError, match="read-only"):
            store.add(rec)
        assert store.direct_items() == []

    def test_load_from_csv(self, tmp_path):
        csv_path = tmp_path / "evidence.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "record_id",
                    "paper_title",
                    "method_domain",
                    "item_id",
                    "field",
                    "value",
                    "confidence",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "record_id": "r1",
                    "paper_title": "P1",
                    "method_domain": "qc",
                    "item_id": "i1",
                    "field": "sci",
                    "value": "0.8",
                    "confidence": "direct",
                }
            )

        store = EvidenceStore()
        count = store.load_from_csv(csv_path)
        assert count == 1
        assert len(store.all()) == 1


class TestMethodLibrary:
    def test_builtin_methods(self):
        lib = MethodLibrary()
        for m in BUILTIN_METHODS:
            lib.register(m)
        assert len(lib.all_ids()) == len(BUILTIN_METHODS)

    def test_get_method(self):
        lib = MethodLibrary()
        for m in BUILTIN_METHODS:
            lib.register(m)
        m = lib.get("optical_density")
        assert m is not None
        assert m.domain == "preprocessing"

    def test_by_domain(self):
        lib = MethodLibrary()
        for m in BUILTIN_METHODS:
            lib.register(m)
        qc_methods = lib.by_domain("qc")
        assert len(qc_methods) > 0


class TestRiskRuleLibrary:
    def test_builtin_rules(self):
        lib = RiskRuleLibrary()
        for r in BUILTIN_RISK_RULES:
            lib.register(r)
        assert len(lib.all_ids()) == len(BUILTIN_RISK_RULES)

    def test_get_rule(self):
        lib = RiskRuleLibrary()
        for r in BUILTIN_RISK_RULES:
            lib.register(r)
        r = lib.get("qc-sci-threshold")
        assert r is not None
        assert r.severity == "medium"


class TestPresetLibrary:
    def test_builtin_presets(self):
        lib = PresetLibrary()
        for p in BUILTIN_PRESETS:
            lib.register(p)
        assert len(lib.all_ids()) == len(BUILTIN_PRESETS)

    def test_get_preset(self):
        lib = PresetLibrary()
        for p in BUILTIN_PRESETS:
            lib.register(p)
        p = lib.get("conservative_qc")
        assert p is not None
        assert p.parameters["sci_threshold"] == 0.8


class TestNodeLibrary:
    def test_builtin_templates(self):
        lib = NodeLibrary()
        for t in ALL_NODE_TEMPLATES:
            lib.register(t)
        assert len(lib.all_ids()) == len(ALL_NODE_TEMPLATES)

    def test_create_atom_from_template(self):
        lib = NodeLibrary()
        for t in ALL_NODE_TEMPLATES:
            lib.register(t)
        atom = lib.create_atom("optical_density")
        assert atom is not None
        assert atom.type == "optical_density"
        assert len(atom.ports) == 2

    def test_create_atom_unknown_returns_none(self):
        lib = NodeLibrary()
        assert lib.create_atom("nonexistent") is None
