"""Risk classification (Phase 2 governance input).

Deterministic rules over intent + plan + repo. High risk always routes to
human approval before any mutation; the reasons travel with the run so
reviewers see exactly why.
"""
from __future__ import annotations

from ..common.models import CandidatePlan, RepositoryContext, RiskLevel, UserIntent


def classify_risk(
    intent: UserIntent,
    plan: CandidatePlan,
    repo_ctx: RepositoryContext,
    target_branch: str,
    publish: bool,
    protected_branches: list[str],
) -> tuple[RiskLevel, list[str]]:
    high: list[str] = []
    medium: list[str] = []

    if intent.deployment_target == "production":
        high.append("targets production deployment")
    if plan.removes_security:
        high.append("removes or weakens a security control")
    if plan.cloud_oidc and intent.deployment_target == "production":
        high.append("requests production cloud credentials via OIDC")
    if publish and target_branch in protected_branches and plan.touches_security:
        high.append(f"publishes security-relevant CI directly toward protected branch '{target_branch}'")

    writes = [scope for scope, value in plan.permissions.items() if value == "write"]
    if writes:
        medium.append(f"requests write permissions: {', '.join(writes)}")
    if publish:
        medium.append("will create a branch/commit/PR on github")
    if repo_ctx.is_fork and publish:
        medium.append("operates on a forked repository")
    if plan.touches_security and publish:
        medium.append("touches security-sensitive pipeline behavior")
    if plan.has_deploy_job:
        medium.append("contains a deployment job")

    if high:
        return RiskLevel.HIGH, high + medium
    if medium:
        return RiskLevel.MEDIUM, medium
    return RiskLevel.LOW, ["read-only plan, no deployment, no elevated permissions"]
