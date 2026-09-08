"""Policy facade: builds the OPA input document and evaluates it.

Semantics (PDF §3 fail closed): OPA server when configured; unreachable OPA
with OPA_URL set FAILS the run. The local mirror runs only when OPA_URL is
empty (dev/test) and says so in its provenance.
"""
from __future__ import annotations

from ..common.models import CandidatePlan, PolicyDecision, RepositoryContext, UserIntent
from ..config import Settings
from ..observability.logging import get_logger
from ..observability.metrics import POLICY_DECISIONS
from .catalog import get_catalog
from .local import evaluate_local
from .opa import OPAClient, OPAError

LOG = get_logger("ci_agent.policy")


class PolicyError(RuntimeError):
    pass


def build_policy_input(
    intent: UserIntent,
    plan: CandidatePlan,
    repo_ctx: RepositoryContext,
    risk_level: str,
    target_branch: str,
    publish: bool,
) -> dict:
    return {
        "intent": {
            "platform": intent.platform,
            "capabilities": intent.capabilities,
            "prohibited_tools": intent.prohibited_tools,
            "target_branch": target_branch,
            "deployment_target": intent.deployment_target,
            "publish": publish,
        },
        "plan": {
            "tools": [
                {"name": t.name, "version": t.version, "capability": t.capability}
                for t in plan.tools
            ],
            "actions": [{"uses": a.uses, "pinned": a.pinned} for a in plan.actions],
            "permissions": plan.permissions,
            "licenses": plan.licenses,
            "has_deploy_job": plan.has_deploy_job,
            "touches_security": plan.touches_security,
            "removes_security": plan.removes_security,
            "cloud_oidc": plan.cloud_oidc,
        },
        "repo": {
            "default_branch": repo_ctx.default_branch,
            "is_fork": repo_ctx.is_fork,
        },
        "risk": {"level": risk_level},
    }


async def evaluate_policy(
    intent: UserIntent,
    plan: CandidatePlan,
    repo_ctx: RepositoryContext,
    risk_level: str,
    target_branch: str,
    publish: bool,
    settings: Settings,
) -> PolicyDecision:
    catalog = get_catalog(settings)
    opa_input = build_policy_input(intent, plan, repo_ctx, risk_level, target_branch, publish)
    if settings.opa_url:
        try:
            decision = await OPAClient(settings).evaluate(opa_input)
        except OPAError as exc:
            LOG.error("OPA unreachable, failing closed err=%s", exc)
            raise PolicyError(f"policy engine unreachable — failing closed: {exc}") from exc
    else:
        decision = evaluate_local(opa_input, catalog)
        LOG.warning("OPA_URL unset — evaluated with local mirror (dev/test only)")
    POLICY_DECISIONS.labels(decision=decision.decision.value, evaluator=decision.evaluator).inc()
    LOG.info("policy decision=%s deny=%d approvals=%d evaluator=%s",
             decision.decision.value, len(decision.deny), len(decision.approval_reasons), decision.evaluator)
    return decision
