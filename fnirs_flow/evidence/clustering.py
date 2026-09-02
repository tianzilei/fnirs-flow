"""Conservative study/report clustering using only explicit hard edges."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ClusterRelation(str, Enum):
    SAME = "same"
    DISTINCT = "distinct"
    SUSPECTED = "suspected"
    UNKNOWN = "unknown"


class ClusterEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    left_report_id: str
    right_report_id: str
    relation: ClusterRelation
    rule_id: str
    rule_version: str
    evidence: tuple[str, ...] = ()
    confidence_features: dict[str, str | float | int | bool] = Field(default_factory=dict)
    hard_rule: bool = False


def conservative_components(report_ids: tuple[str, ...], edges: tuple[ClusterEdge, ...]) -> tuple[tuple[str, ...], ...]:
    parent = {item: item for item in report_ids}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for edge in sorted(edges, key=lambda item: (item.left_report_id, item.right_report_id, item.rule_id)):
        if edge.relation is not ClusterRelation.SAME or not edge.hard_rule:
            continue
        if edge.left_report_id not in parent or edge.right_report_id not in parent:
            continue
        left, right = find(edge.left_report_id), find(edge.right_report_id)
        if left != right:
            parent[max(left, right)] = min(left, right)
    groups: dict[str, list[str]] = {}
    for item in sorted(report_ids):
        groups.setdefault(find(item), []).append(item)
    return tuple(tuple(values) for _, values in sorted(groups.items()))
