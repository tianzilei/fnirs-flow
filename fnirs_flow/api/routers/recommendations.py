"""Recommendation endpoints backed by the v1.3 domain contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from fnirs_flow.api.router_dependencies import bind_router_context, current_store
from fnirs_flow.recommendation import build_static_decision, confirm_decision
from fnirs_flow.recommendation.diff import decision_diff, reevaluate_decision
from fnirs_flow.recommendation.store import RecommendationStore

router = APIRouter(dependencies=[Depends(bind_router_context)])


def _dump(decision: Any) -> dict[str, Any]:
    return cast(dict[str, Any], decision.model_dump(mode="json"))


def _recommendation_store() -> RecommendationStore:
    """Resolve storage from the configured project store, never the CWD."""
    project_store = current_store()
    return RecommendationStore(Path(project_store._base_dir) / "recommendation_decisions.jsonl")


class StaticRecommendationRequest(BaseModel):
    scenario: str
    slot_id: str
    candidate_id: str
    reasons: list[str] = Field(default_factory=list)


class RecommendationConfirmationRequest(BaseModel):
    confirmed_by: str = Field(min_length=1, max_length=200)


@router.post("/api/recommendations/static")
async def create_static_recommendation(request: StaticRecommendationRequest) -> dict[str, Any]:
    decision = build_static_decision(
        scenario=request.scenario,
        slot_id=request.slot_id,
        candidate_id=request.candidate_id,
        reasons=tuple(request.reasons),
    )
    _recommendation_store().save(decision)
    return dict(decision.model_dump(mode="json"))


@router.get("/api/recommendations/{decision_id}")
async def get_recommendation(decision_id: str) -> dict[str, Any]:
    decision = _recommendation_store().get(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Recommendation decision not found")
    return dict(decision.model_dump(mode="json"))


@router.post("/api/recommendations/{decision_id}/confirm")
async def confirm_recommendation(decision_id: str, request: RecommendationConfirmationRequest) -> dict[str, Any]:
    store = _recommendation_store()
    previous = store.get(decision_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="Recommendation decision not found")
    try:
        decision = confirm_decision(previous, confirmed_by=request.confirmed_by)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.save(decision)
    return {"decision": decision.model_dump(mode="json"), "supersedes_decision_id": previous.decision_id}


@router.post("/api/projects/{project_id}/recommendations/static")
async def create_project_recommendation(project_id: str, request: StaticRecommendationRequest) -> dict[str, Any]:
    store = current_store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    decision = build_static_decision(
        scenario=request.scenario, slot_id=request.slot_id,
        candidate_id=request.candidate_id, reasons=tuple(request.reasons),
    )
    store.save_recommendation_decision(project_id, decision)
    return _dump(decision)


@router.get("/api/projects/{project_id}/recommendations")
async def get_current_project_recommendation(project_id: str) -> dict[str, Any]:
    decision = current_store().get_recommendation_decision(project_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Recommendation decision not found")
    return _dump(decision)


@router.post("/api/projects/{project_id}/recommendations/{decision_id}/confirm")
async def confirm_project_recommendation(
    project_id: str, decision_id: str, request: RecommendationConfirmationRequest
) -> dict[str, Any]:
    store = current_store()
    previous = store.get_recommendation_decision(project_id, decision_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="Recommendation decision not found")
    try:
        decision = confirm_decision(previous, confirmed_by=request.confirmed_by)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.save_recommendation_decision(project_id, decision)
    return {"decision": decision.model_dump(mode="json"), "supersedes_decision_id": previous.decision_id}


@router.get("/api/projects/{project_id}/recommendations/{decision_id}")
async def get_project_recommendation(project_id: str, decision_id: str) -> dict[str, Any]:
    decision = current_store().get_recommendation_decision(project_id, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Recommendation decision not found")
    return _dump(decision)


@router.post("/api/projects/{project_id}/recommendations/{decision_id}/reevaluate")
async def reevaluate_project_recommendation(project_id: str, decision_id: str) -> dict[str, Any]:
    store = current_store()
    previous = store.get_recommendation_decision(project_id, decision_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="Recommendation decision not found")
    decision = reevaluate_decision(previous)
    store.save_recommendation_decision(project_id, decision)
    return {"decision": decision.model_dump(mode="json"), "diff": decision_diff(previous, decision)}


@router.get("/api/projects/{project_id}/recommendations/{from_id}/diff/{to_id}")
async def diff_project_recommendations(project_id: str, from_id: str, to_id: str) -> dict[str, Any]:
    store = current_store()
    before = store.get_recommendation_decision(project_id, from_id)
    after = store.get_recommendation_decision(project_id, to_id)
    if before is None or after is None:
        raise HTTPException(status_code=404, detail="Recommendation decision not found")
    return decision_diff(before, after)
