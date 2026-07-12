"""Risk and readiness validation models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RiskItem(BaseModel):
    risk_id: str
    rule_id: str = ""
    code: str = Field(
        default="",
        description="Typed error code for filtering",
    )
    severity: str = Field(pattern="^(low|medium|high|fatal)$")
    domain: str = Field(
        pattern=(
            "^(schema|graph|adapter|security|qc|design|analysis|reproducibility|reporting|harmonization|multi_site)$"
        )
    )
    affected_object: str = ""
    subject: str = ""
    session: str = ""
    run: str = ""
    message: str
    rationale: str = ""
    suggested_action: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    status: str = Field(default="open", pattern="^(open|acknowledged|resolved|ignored)$")


class ReadinessCheck(BaseModel):
    name: str
    status: str = Field(pattern="^(pass|warn|fail|skip)$")
    message: str = ""


class ReadinessResult(BaseModel):
    status: str = Field(pattern="^(Ready|Needs Attention|Blocked)$")
    checks: list[ReadinessCheck] = Field(default_factory=list)


class ValidationReport(BaseModel):
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    risks: list[RiskItem] = Field(default_factory=list)
    readiness: ReadinessResult | None = None

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def has_fatal_risks(self) -> bool:
        return any(r.severity == "fatal" for r in self.risks)

    def derive_readiness(self) -> ReadinessResult:
        """Derive action readiness from validation errors, warnings, and risks."""
        checks: list[ReadinessCheck] = []

        if self.errors:
            checks.append(
                ReadinessCheck(
                    name="schema_graph_validation",
                    status="fail",
                    message=f"{len(self.errors)} validation error(s)",
                )
            )
        else:
            checks.append(
                ReadinessCheck(
                    name="schema_graph_validation",
                    status="pass",
                    message="No validation errors",
                )
            )

        fatal_count = sum(1 for risk in self.risks if risk.severity == "fatal")
        high_count = sum(1 for risk in self.risks if risk.severity == "high")
        attention_count = sum(1 for risk in self.risks if risk.severity in {"medium", "high"})

        if fatal_count:
            checks.append(
                ReadinessCheck(
                    name="fatal_risks",
                    status="fail",
                    message=f"{fatal_count} fatal risk(s)",
                )
            )
        elif high_count:
            checks.append(
                ReadinessCheck(
                    name="high_risks",
                    status="warn",
                    message=f"{high_count} high risk(s)",
                )
            )
        else:
            checks.append(
                ReadinessCheck(
                    name="blocking_risks",
                    status="pass",
                    message="No fatal or high risks",
                )
            )

        if self.warnings or attention_count:
            checks.append(
                ReadinessCheck(
                    name="attention_items",
                    status="warn",
                    message=(f"{len(self.warnings)} warning(s), {attention_count} medium/high risk(s)"),
                )
            )
        else:
            checks.append(
                ReadinessCheck(
                    name="attention_items",
                    status="pass",
                    message="No attention items",
                )
            )

        if self.errors or fatal_count:
            status = "Blocked"
        elif self.warnings or attention_count:
            status = "Needs Attention"
        else:
            status = "Ready"

        return ReadinessResult(status=status, checks=checks)
