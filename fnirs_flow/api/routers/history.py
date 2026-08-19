"""FlowVCS design history endpoints."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException

from fnirs_flow.api.error_responses import api_error
from fnirs_flow.api.models import CheckoutResponse, CommitIdResponse, DesignHistoryStatus, HistoryMigrationReport
from fnirs_flow.api.router_dependencies import bind_router_context, current_store
from fnirs_flow.history.models import BranchInfo, CommitLogEntry, DesignCommit, DiffResult

router = APIRouter(dependencies=[Depends(bind_router_context)])


def _store() -> Any:
    return current_store()


@router.post("/api/projects/{project_id}/history/initialize", response_model=CommitIdResponse)
async def initialize_design_history_endpoint(project_id: str) -> dict[str, str]:
    try:
        commit_id = _store().initialize_design_history(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"commit_id": commit_id}


@router.get("/api/projects/{project_id}/history", response_model=DesignHistoryStatus)
async def get_design_history_endpoint(project_id: str) -> dict[str, Any]:
    store = _store()
    head = store.get_design_head(project_id)
    if head is None:
        return {"head": None, "branches": [], "dirty": False}
    return {
        "head": head,
        "branches": store.list_design_branches(project_id),
        "dirty": store.is_design_dirty(project_id),
    }


@router.get("/api/projects/{project_id}/history/commits", response_model=list[CommitLogEntry])
async def list_design_commits_endpoint(
    project_id: str, branch: str | None = None, limit: int = 50, offset: int = 0
) -> Any:
    return _store().list_design_commits(project_id, branch, limit=limit, offset=offset)


@router.get("/api/projects/{project_id}/history/commits/{commit_id}", response_model=DesignCommit)
async def get_design_commit_endpoint(project_id: str, commit_id: str) -> dict[str, Any]:
    from fnirs_flow.history.errors import CommitNotFound

    try:
        return cast(dict[str, Any], _store()._history_service(project_id).get_commit(commit_id).model_dump())
    except CommitNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/projects/{project_id}/history/commits", response_model=CommitIdResponse)
async def create_design_commit_endpoint(project_id: str, body: dict[str, Any]) -> dict[str, str]:
    from fnirs_flow.history.errors import NoChanges

    try:
        return {
            "commit_id": _store().commit_design(
                project_id,
                body.get("message", ""),
                reason=body.get("reason", "manual_design_commit"),
            )
        }
    except NoChanges as exc:
        raise api_error(
            409,
            "NO_CHANGES",
            str(exc),
            "design_commit",
            recoverable=True,
            suggested_action="Modify the flow before committing",
        ) from exc


@router.get("/api/projects/{project_id}/history/diff", response_model=DiffResult)
async def design_diff_endpoint(project_id: str, from_commit: str = "", to_commit: str = "") -> Any:
    if not from_commit or not to_commit:
        raise HTTPException(status_code=422, detail="Both from_commit and to_commit are required")
    try:
        return _store().get_design_diff(project_id, from_commit, to_commit)
    except (ValueError, KeyError, OSError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/projects/{project_id}/history/branches", response_model=BranchInfo)
async def create_design_branch_endpoint(project_id: str, body: dict[str, Any]) -> Any:
    from fnirs_flow.history.errors import BranchAlreadyExists, BranchNameInvalid

    try:
        return _store().create_design_branch(project_id, body.get("name", ""), body.get("from_commit_id"))
    except BranchNameInvalid as exc:
        raise api_error(
            422,
            "BRANCH_NAME_INVALID",
            str(exc),
            "branch_create",
            recoverable=True,
            suggested_action="Use a valid branch name",
        ) from exc
    except BranchAlreadyExists as exc:
        raise api_error(
            409,
            "BRANCH_ALREADY_EXISTS",
            str(exc),
            "branch_create",
            recoverable=True,
            suggested_action="Use a different branch name",
        ) from exc


@router.delete("/api/projects/{project_id}/history/branches/{name}")
async def delete_design_branch_endpoint(project_id: str, name: str) -> dict[str, str]:
    from fnirs_flow.history.errors import BranchNotFound

    try:
        _store().delete_design_branch(project_id, name)
    except BranchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted"}


@router.post("/api/projects/{project_id}/history/checkout", response_model=CheckoutResponse)
async def checkout_design_branch_endpoint(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    from fnirs_flow.history.errors import BranchNotFound

    target = body.get("target", "")
    try:
        return {"flow": _store().switch_design_branch(project_id, target), "target": target}
    except BranchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/projects/{project_id}/history/migrate", response_model=HistoryMigrationReport)
async def migrate_design_history_endpoint(project_id: str) -> Any:
    try:
        return _store().migrate_snapshots_to_history(project_id)
    except Exception as exc:
        raise api_error(
            500,
            "MIGRATION_FAILED",
            str(exc),
            "history_migration",
            recoverable=True,
            suggested_action="Check project snapshots and retry",
        ) from exc
