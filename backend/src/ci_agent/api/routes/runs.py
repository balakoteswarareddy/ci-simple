"""Run lifecycle endpoints: create, inspect, approve, refresh checks."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field

from ...agent.orchestrator import Orchestrator
from ...common.models import ApprovalInput, PipelineIR, PolicyDecision, RunOptions, ValidationResult
from ...config import Settings, get_settings
from ...evidence.store import EvidenceStore
from ...integrations.github import GitHubClient, merge_recommendation, parse_repo_url
from ...pipeline.render import render as render_ir
from ...security.auth import get_actor
from ...validation.runner import all_passed
from ..deps import get_orchestrator, get_store

router = APIRouter(tags=["runs"])


class CreateRunRequest(BaseModel):
    repo_url: str = Field(min_length=1, max_length=2000)
    request: str = Field(min_length=1, max_length=8000)
    options: RunOptions = Field(default_factory=RunOptions)


class DecideRequest(BaseModel):
    approver: str = ""
    decision: str = "approve"
    reason: str = ""


@router.post("/runs", status_code=202)
async def create_run(
    body: CreateRunRequest,
    background: BackgroundTasks,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> dict:
    run_id = await orchestrator.start_run(body.repo_url.strip(), body.request.strip(), body.options)
    background.add_task(orchestrator.execute, run_id)
    return {"run_id": run_id, "status": "queued"}


@router.get("/runs")
async def list_runs(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    store: EvidenceStore = Depends(get_store),
) -> dict:
    return {"runs": store.list_runs(limit=limit, status=status)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, store: EvidenceStore = Depends(get_store)) -> dict:
    row = store.get_run(run_id)
    if row is None:
        raise KeyError(f"unknown run {run_id}")
    return row


@router.get("/runs/{run_id}/events")
async def get_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    store: EvidenceStore = Depends(get_store),
) -> dict:
    if store.get_run(run_id) is None:
        raise KeyError(f"unknown run {run_id}")
    return {"run_id": run_id, "events": store.list_events(run_id, after_seq=after_seq)}


@router.get("/runs/{run_id}/yaml")
async def get_yaml(run_id: str, store: EvidenceStore = Depends(get_store)) -> dict:
    row = store.get_run(run_id)
    if row is None:
        raise KeyError(f"unknown run {run_id}")
    filename = (row.get("publish") or {}).get("file", "")
    if not filename and row.get("ir"):
        filename = render_ir(PipelineIR(**row["ir"])).filename
    return {"filename": filename or "workflow.yml", "content": row.get("rendered_yaml", "")}


@router.get("/runs/{run_id}/evidence")
async def get_evidence(run_id: str, store: EvidenceStore = Depends(get_store)) -> dict:
    evidence = store.get_evidence(run_id)
    if evidence is None:
        raise KeyError(f"no evidence recorded for run {run_id} yet")
    return evidence


@router.post("/runs/{run_id}/approve")
async def decide_run(
    run_id: str,
    body: DecideRequest,
    actor: str = Depends(get_actor),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> dict:
    if body.decision not in ("approve", "reject"):
        raise ValueError("decision must be 'approve' or 'reject'")
    approver = body.approver.strip() or actor
    approval = ApprovalInput(approver=approver, decision=body.decision, reason=body.reason[:2000])  # type: ignore[arg-type]
    return {"run_id": run_id, **await orchestrator.decide(run_id, approval)}


@router.post("/runs/{run_id}/checks/refresh")
async def refresh_checks(
    run_id: str,
    store: EvidenceStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Re-read PR check runs + merge recommendation (Phase 5/6 observation)."""
    row = store.get_run(run_id)
    if row is None:
        raise KeyError(f"unknown run {run_id}")
    publish = row.get("publish") or {}
    if not publish.get("commit_sha"):
        raise ValueError("run has no published commit to observe")
    client = GitHubClient(settings)
    repo = parse_repo_url(row["repo_url"])
    checks = await client.list_check_runs(repo, publish["commit_sha"])
    policy = PolicyDecision(**row["policy"]) if row.get("policy") else None
    results = [ValidationResult(**r) for r in (row.get("validation") or [])]
    merge = merge_recommendation(checks, policy.decision.value if policy else "DENY", all_passed(results))
    publish["checks"] = checks
    publish["merge"] = merge
    store.update_run(run_id, publish=publish)
    store.append_event(run_id, "publish.observe", "info",
                       f"checks refreshed: {merge['recommendation']}", {"merge": merge})
    return {"run_id": run_id, "checks": checks, "merge": merge}
