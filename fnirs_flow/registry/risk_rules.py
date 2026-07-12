"""Risk rules: validation rules derived from literature and best practices."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RiskRule(BaseModel):
    rule_id: str
    name: str
    domain: str  # schema, graph, adapter, security, qc, design, analysis,
    # reproducibility, reporting
    severity: str = "medium"
    condition: str = ""  # human-readable condition description
    message_template: str = ""
    suggested_action: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    reference: str = ""


class RiskRuleLibrary:
    def __init__(self) -> None:
        self._rules: dict[str, RiskRule] = {}

    def register(self, rule: RiskRule) -> None:
        self._rules[rule.rule_id] = rule

    def get(self, rule_id: str) -> RiskRule | None:
        return self._rules.get(rule_id)

    def by_domain(self, domain: str) -> list[RiskRule]:
        return [r for r in self._rules.values() if r.domain == domain]

    def all_ids(self) -> list[str]:
        return sorted(self._rules.keys())


# Built-in risk rules
BUILTIN_RISK_RULES: list[RiskRule] = [
    RiskRule(
        rule_id="qc-sci-threshold",
        name="SCI Quality Threshold",
        domain="qc",
        severity="medium",
        condition="Scalp Coupling Index below threshold",
        message_template="SCI below {threshold} for {n_channels} channels",
        suggested_action="Review affected channels for signal quality",
        reference="Best practices for fNIRS publications",
    ),
    RiskRule(
        rule_id="qc-sd-distance",
        name="Source-Detector Distance",
        domain="qc",
        severity="high",
        condition="Source-detector distance outside valid range",
        message_template="SD distance {distance}m outside {min}-{max}m range",
        suggested_action="Check channel placement or exclude channels",
        reference="NIRS-BIDS specification",
    ),
    RiskRule(
        rule_id="design-no-contrasts",
        name="Missing Contrasts",
        domain="design",
        severity="medium",
        condition="No contrasts defined",
        message_template="No contrasts defined for statistical analysis",
        suggested_action="Define at least one contrast of interest",
        reference="fNIRS analysis best practices",
    ),
    RiskRule(
        rule_id="reproducibility-no-seed",
        name="Missing Random Seed",
        domain="reproducibility",
        severity="low",
        condition="No random seed specified",
        message_template="No random seed for reproducibility",
        suggested_action="Set a fixed random seed for reproducible results",
        reference="Reproducibility guidelines",
    ),
]
