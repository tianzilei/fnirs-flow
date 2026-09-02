from fnirs_flow.execution.models import ExecutionRequest
from fnirs_flow.execution.provenance import ProvenanceRecord


def test_recommendation_anchor_is_written_to_provenance() -> None:
    request = ExecutionRequest(
        project_dir="/tmp/project",
        recommendation_decision_id="dec-123",
        recommendation_rules_version="1.3.0-static",
    )
    provenance = ProvenanceRecord()
    provenance.set_recommendation_anchor(
        decision_id=request.recommendation_decision_id,
        rules_version=request.recommendation_rules_version,
    )
    provenance.log(step_id="execution/test", parameters={})
    record = provenance.all()[0]
    assert record["recommendation_decision_id"] == "dec-123"
    assert record["recommendation_rules_version"] == "1.3.0-static"
