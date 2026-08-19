"""Structured Flow diff for FlowVCS."""

from __future__ import annotations

from typing import Any

from fnirs_flow.flow.serialization import normalize_flow_payload
from fnirs_flow.history.models import DiffChange


def compute_flow_diff(from_flow: dict[str, Any], to_flow: dict[str, Any]) -> list[DiffChange]:
    """Compute structural changes between two flow dicts.

    Aligns nodes by ``id`` and edges by ``id`` (or the composite key
    ``(source, source_port, target, target_port)`` when no edge ID exists).
    """
    changes: list[DiffChange] = []
    from_flow = normalize_flow_payload(from_flow)
    to_flow = normalize_flow_payload(to_flow)

    # --- Nodes ---
    from_nodes = {n.get("id", ""): n for n in from_flow.get("flow_atoms", [])}
    to_nodes = {n.get("id", ""): n for n in to_flow.get("flow_atoms", [])}

    for nid in sorted(set(from_nodes) - set(to_nodes)):
        changes.append(DiffChange(kind="node_removed", node_id=nid))
    for nid in sorted(set(to_nodes) - set(from_nodes)):
        changes.append(DiffChange(kind="node_added", node_id=nid))
    for nid in sorted(set(from_nodes) & set(to_nodes)):
        fn, tn = from_nodes[nid], to_nodes[nid]
        for key in sorted(set(fn) | set(tn)):
            if key == "id":
                continue
            fv, tv = fn.get(key), tn.get(key)
            if fv != tv:
                changes.append(
                    DiffChange(
                        kind="node_changed",
                        node_id=nid,
                        path=key,
                        before=fv,
                        after=tv,
                    )
                )

    # --- Edges ---
    def _edge_key(e: dict[str, Any]) -> str:
        eid: str = e.get("id", "")
        if eid:
            return eid
        src = f"{e.get('source', '')}:{e.get('source_port', '')}"
        tgt = f"{e.get('target', '')}:{e.get('target_port', '')}"
        return f"{src}->{tgt}"

    from_edges = {_edge_key(e): e for e in from_flow.get("edges", [])}
    to_edges = {_edge_key(e): e for e in to_flow.get("edges", [])}

    for eid in sorted(set(from_edges) - set(to_edges)):
        changes.append(DiffChange(kind="edge_removed", edge_id=eid))
    for eid in sorted(set(to_edges) - set(from_edges)):
        changes.append(DiffChange(kind="edge_added", edge_id=eid))
    for eid in sorted(set(from_edges) & set(to_edges)):
        fe, te = from_edges[eid], to_edges[eid]
        for key in sorted(set(fe) | set(te)):
            if key == "id":
                continue
            fv, tv = fe.get(key), te.get(key)
            if fv != tv:
                changes.append(
                    DiffChange(
                        kind="edge_changed",
                        edge_id=eid,
                        path=key,
                        before=fv,
                        after=tv,
                    )
                )

    return changes
