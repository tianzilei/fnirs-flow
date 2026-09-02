from fastapi.testclient import TestClient

from fnirs_flow.api.app import app


def test_static_recommendation_api_round_trip() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/recommendations/static",
            json={"scenario": "task_glm", "slot_id": "filter_slot", "candidate_id": "A1"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["source_mode"] == "rule_based_fallback"
        assert payload["tier"] == "recommended"
        fetched = client.get(f"/api/recommendations/{payload['decision_id']}")
        assert fetched.status_code == 200
        assert fetched.json() == payload
