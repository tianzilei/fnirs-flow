"""Failure store: records and manages structured execution failures."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class FailureRecord(BaseModel):
    """Structured failure information per subject/session/run/atom."""

    failure_id: str
    subject: str = ""
    session: str = ""
    run: str = ""
    atom_id: str = ""
    exception_type: str = ""
    message: str = ""
    recoverable: bool = False
    log_path: str | None = None
    timestamp: str = ""


class ActionAttempt(BaseModel):
    """Tracks execution attempts at subject/session/run granularity."""

    attempt_id: str
    subject: str = ""
    session: str = ""
    run: str = ""
    atom_id: str = ""
    status: str = Field(
        default="planned",
        pattern="^(planned|running|completed|failed|partial)$",
    )
    started_at: str = ""
    completed_at: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    recoverable: bool = False
    log_path: str | None = None
    risks: list[dict[str, Any]] = Field(default_factory=list)


class FailureStore:
    def __init__(self) -> None:
        self._failures: list[FailureRecord] = []

    def register(
        self,
        subject: str = "",
        session: str = "",
        run: str = "",
        atom_id: str = "",
        exception_type: str = "RuntimeError",
        message: str = "",
        recoverable: bool = False,
        log_path: str | None = None,
    ) -> FailureRecord:
        failure = FailureRecord(
            failure_id=f"fail-{subject}_{session}_{run}_{atom_id}",
            subject=subject,
            session=session,
            run=run,
            atom_id=atom_id,
            exception_type=exception_type,
            message=message,
            recoverable=recoverable,
            log_path=log_path,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._failures.append(failure)
        return failure

    def register_attempt(self, attempt: ActionAttempt) -> None:
        """Register a failed ActionAttempt as a FailureRecord."""
        if attempt.status == "failed":
            self.register(
                subject=attempt.subject,
                session=attempt.session,
                run=attempt.run,
                atom_id=attempt.atom_id,
                exception_type=attempt.error_type or "RuntimeError",
                message=attempt.error_message or "",
                recoverable=attempt.recoverable,
                log_path=attempt.log_path,
            )

    def all(self) -> list[FailureRecord]:
        return list(self._failures)

    def write_csv(self, outdir: Path) -> Path:
        path = outdir / "failure_manifest.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "failure_id",
                    "subject",
                    "session",
                    "run",
                    "atom_id",
                    "exception_type",
                    "message",
                    "recoverable",
                    "log_path",
                    "timestamp",
                ]
            )
            for rec in self._failures:
                writer.writerow(
                    [
                        rec.failure_id,
                        rec.subject,
                        rec.session,
                        rec.run,
                        rec.atom_id,
                        rec.exception_type,
                        rec.message,
                        rec.recoverable,
                        rec.log_path or "",
                        rec.timestamp,
                    ]
                )
        return path

    def write_json(self, outdir: Path) -> Path:
        path = outdir / "failure_manifest.json"
        data = [rec.model_dump() for rec in self._failures]
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path
