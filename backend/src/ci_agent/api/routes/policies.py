"""Policy introspection endpoints (Phase 2 governance)."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...common.models import CandidatePlan, RepositoryContext, UserIntent
from ...config import Settings, get_settings
from ...policy.catalog import get_catalog
from ...policy.engine import evaluate_policy

router = APIRouter(tags=["policies"])


class EvaluateRequest(BaseModel):
    intent: dict = Field(default_factory=dict)
    plan: dict = Field(default_factory=dict)
    repo: dict = Field(default_factory=dict)
    risk_level: str = "low"
    target_branch: str = ""
    publish: bool = False


@router.get("/policies/catalog")
async def get_policy_catalog(settings: Settings = Depends(get_settings)) -> dict:
    return asdict(get_catalog(settings))


@router.post("/policies/evaluate")
async def evaluate_adhoc(body: EvaluateRequest, settings: Settings = Depends(get_settings)) -> dict:
    intent = UserIntent(**body.intent)
    plan = CandidatePlan(**body.plan)
    repo = RepositoryContext(repo_url=body.repo.get("repo_url", ""), **{
        k: v for k, v in body.repo.items() if k != "repo_url"})
    decision = await evaluate_policy(
        intent, plan, repo, body.risk_level, body.target_branch, body.publish, settings)
    return decision.model_dump()
