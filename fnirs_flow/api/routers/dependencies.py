"""Dependency resolution, approval, and environment management endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException

from fnirs_flow.api.router_dependencies import bind_router_context, current_store

router = APIRouter(dependencies=[Depends(bind_router_context)])


def _store() -> Any:
    return current_store()


@router.post("/api/dependencies/resolve")
async def resolve_dependencies_endpoint(project_id: str) -> dict[str, Any]:
    from fnirs_flow.api.transaction import ProjectTransaction
    from fnirs_flow.dependencies.resolver import resolve_dependencies

    store = _store()
    with ProjectTransaction(store, project_id, reason="dependency_plan_resolved") as tx:
        compiled_dir = tx.output_dir / "compiled"
        if not compiled_dir.exists():
            raise HTTPException(status_code=404, detail="Project not compiled yet")
        dag_path = compiled_dir / "execution_dag.json"
        if not dag_path.exists():
            raise HTTPException(status_code=404, detail="execution_dag.json not found")
        dag = json.loads(dag_path.read_text(encoding="utf-8"))
        plan = resolve_dependencies(dag, flow_id=project_id)
        (compiled_dir / "dependency_plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        tx.commit()
    return cast(dict[str, Any], plan.model_dump())


def _find_plan(plan_id: str) -> tuple[dict[str, Any], str] | None:
    store = _store()
    for project in store.list_all():
        path = store.get_output_dir(project.id) / "compiled" / "dependency_plan.json"
        if path.exists():
            plan = json.loads(path.read_text(encoding="utf-8"))
            if plan.get("plan_id") == plan_id:
                return plan, project.id
    return None


@router.get("/api/dependencies/plans/{plan_id}")
async def get_dependency_plan(plan_id: str) -> dict[str, Any]:
    found = _find_plan(plan_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return found[0]


async def _record_approval(plan_id: str) -> dict[str, Any]:
    from fnirs_flow.api.transaction import ProjectTransaction
    from fnirs_flow.dependencies.models import ApprovalRecord, DependencyPlan, InstallPolicy
    from fnirs_flow.dependencies.policies import get_policy_manager

    found = _find_plan(plan_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    plan_data, project_id = found
    plan = DependencyPlan.model_validate(plan_data)
    plan_key = f"{plan.plan_id}:{plan.revision}"
    get_policy_manager().approve_plan(plan_key)
    approval = ApprovalRecord(
        plan_id=plan.plan_id,
        plan_revision=plan.revision,
        decision=InstallPolicy.APPROVED_ONCE,
        approved_at=datetime.now(timezone.utc).isoformat(),
    )
    with ProjectTransaction(_store(), project_id, reason="dependency_plan_approved") as tx:
        (tx.output_dir / "compiled" / "approval_record.json").write_text(
            approval.model_dump_json(indent=2), encoding="utf-8"
        )
        tx.commit()
    return {"status": "approval_recorded", "plan_id": plan_id, "revision": plan.revision,
            "installation_started": False, "message": "Approval was recorded; no download or installation was started."}


@router.post("/api/dependencies/plans/{plan_id}/record-approval")
async def record_dependency_plan_approval(plan_id: str) -> dict[str, Any]:
    return await _record_approval(plan_id)


@router.post("/api/dependencies/plans/{plan_id}/approve")
async def approve_dependency_plan(plan_id: str) -> dict[str, Any]:
    return await _record_approval(plan_id)


@router.post("/api/dependencies/plans/{plan_id}/reject")
async def reject_dependency_plan(plan_id: str) -> dict[str, Any]:
    from fnirs_flow.dependencies.models import DependencyPlan
    from fnirs_flow.dependencies.policies import get_policy_manager

    found = _find_plan(plan_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    plan = DependencyPlan.model_validate(found[0])
    get_policy_manager().reject_plan(f"{plan.plan_id}:{plan.revision}")
    return {"status": "rejected", "plan_id": plan_id}


@router.get("/api/dependencies/installations/{task_id}")
async def get_installation_status(task_id: str) -> dict[str, Any]:
    from fnirs_flow.dependencies.installer import get_installation_orchestrator
    for task in get_installation_orchestrator().list_tasks():
        if task.task_id == task_id:
            return cast(dict[str, Any], task.model_dump())
    raise HTTPException(status_code=404, detail="Installation task not found")


@router.post("/api/dependencies/installations/{task_id}/cancel")
async def cancel_installation(task_id: str) -> dict[str, Any]:
    from fnirs_flow.dependencies.installer import get_installation_orchestrator
    if get_installation_orchestrator().cancel(task_id):
        return {"status": "cancelled", "task_id": task_id}
    raise HTTPException(status_code=404, detail="Task not found or already completed")


@router.get("/api/dependency-environments")
async def list_dependency_environments() -> Any:
    from fnirs_flow.dependencies.installer import get_installation_orchestrator
    return get_installation_orchestrator().list_environments()


@router.delete("/api/dependency-environments/{environment_id:path}")
async def delete_dependency_environment(environment_id: str) -> dict[str, Any]:
    from fnirs_flow.dependencies.installer import get_installation_orchestrator
    parts = environment_id.split("/", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid environment_id format")
    if get_installation_orchestrator().remove_environment(parts[0], parts[1]):
        return {"status": "removed", "environment_id": environment_id}
    raise HTTPException(status_code=404, detail="Environment not found")
