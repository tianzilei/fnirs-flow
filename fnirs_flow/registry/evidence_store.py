"""Evidence store: manages literature-derived evidence records."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    item_id: str
    source_paper: str = ""
    field: str = ""
    value: Any = None
    confidence: str = "direct"  # direct, conditional, weak
    notes: str = ""


class EvidenceRecord(BaseModel):
    record_id: str
    paper_title: str = ""
    paper_doi: str = ""
    year: int = 0
    method_domain: str = ""  # preprocessing, analysis, qc, reporting
    items: list[EvidenceItem] = Field(default_factory=list)


class EvidenceStore:
    def __init__(self) -> None:
        self._records: list[EvidenceRecord] = []

    def add(self, record: EvidenceRecord) -> None:
        self._records.append(record)

    def all(self) -> list[EvidenceRecord]:
        return list(self._records)

    def by_domain(self, domain: str) -> list[EvidenceRecord]:
        return [r for r in self._records if r.method_domain == domain]

    def direct_items(self) -> list[EvidenceItem]:
        items = []
        for rec in self._records:
            for item in rec.items:
                if item.confidence == "direct":
                    items.append(item)
        return items

    def load_from_csv(self, path: Path) -> int:
        """Load evidence items from a CSV file. Returns count loaded."""
        count = 0
        if not path.exists():
            return 0
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self._records.append(
                    EvidenceRecord(
                        record_id=row.get("record_id", f"rec-{count}"),
                        paper_title=row.get("paper_title", ""),
                        paper_doi=row.get("paper_doi", ""),
                        method_domain=row.get("method_domain", ""),
                        items=[
                            EvidenceItem(
                                item_id=row.get("item_id", f"item-{count}"),
                                field=row.get("field", ""),
                                value=row.get("value", ""),
                                confidence=row.get("confidence", "direct"),
                            )
                        ],
                    )
                )
                count += 1
        return count
