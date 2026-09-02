"""Append-only persistence for recommendation decisions."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from .contracts import RecommendationDecision


class RecommendationStore:
    """Small JSONL-backed immutable decision store.

    Existing records are never updated. Re-evaluation is represented by a new
    decision whose ``user_override``/reasons may reference the prior ID.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = RLock()

    def save(self, decision: RecommendationDecision) -> RecommendationDecision:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            existing = {item.decision_id for item in self.all()}
            if decision.decision_id in existing:
                raise ValueError(f"Recommendation decision already exists: {decision.decision_id}")
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(decision.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n")
        return decision

    def all(self) -> list[RecommendationDecision]:
        if not self.path.exists():
            return []
        records: list[RecommendationDecision] = []
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    records.append(RecommendationDecision.model_validate_json(line))
        return records

    def get(self, decision_id: str) -> RecommendationDecision | None:
        return next((item for item in self.all() if item.decision_id == decision_id), None)
