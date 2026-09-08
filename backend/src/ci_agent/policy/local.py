"""Local policy evaluator — a Python mirror of the Rego bundle.

Used when OPA_URL is unset (dev/tests). Rule ids and semantics intentionally
match deploy/opa/store/policies/*.rego; tests/evals assert parity on sample
inputs. Production deployments MUST set OPA_URL (fail closed otherwise).
"""
from __future__ import annotations

from ..common.models import Decision, PolicyDecision, PolicyFinding
from ..common.util import utcnow
from .catalog import PolicyCatalog


def evaluate_local(opa_input: dict, catalog: PolicyCatalog) -> PolicyDecision:
    deny: list[PolicyFinding] = []
    approvals: list[PolicyFinding] = []
    intent = opa_input.get("intent", {}) or {}
    plan = opa_input.get("plan", {}) or {}
    repo = opa_input.get("repo", {}) or {}
    risk = opa_input.get("risk", {}) or {}

    # -- malformed input (fail closed) ----------------------------------
    if not isinstance(plan.get("tools"), list):
        deny.append(PolicyFinding(rule="PLAN_MALFORMED", message="input.plan.tools is missing"))
    if not isinstance(plan.get("permissions"), dict):
        deny.append(PolicyFinding(rule="PLAN_MALFORMED", message="input.plan.permissions is missing"))
    if not isinstance(intent.get("capabilities"), list):
        deny.append(PolicyFinding(rule="INTENT_MALFORMED", message="input.intent.capabilities is missing"))

    prohibited = {str(t).lower() for t in intent.get("prohibited_tools", []) or []}

    # -- tools ------------------------------------------------------------
    for tool in plan.get("tools", []) or []:
        name = str(tool.get("name", ""))
        if name not in catalog.tools:
            deny.append(PolicyFinding(rule="TOOL_NOT_APPROVED", message=f"tool '{name}' is not in the approved catalog"))
        if name.lower() in prohibited:
            deny.append(PolicyFinding(rule="TOOL_PROHIBITED", message=f"tool '{name}' was explicitly prohibited by the request"))
        if str(tool.get("version", "")) in ("", "latest", "unknown"):
            approvals.append(PolicyFinding(rule="TOOL_VERSION_UNKNOWN", message=f"tool '{name}' has no pinned version"))
    for cap in intent.get("capabilities", []) or []:
        if cap not in catalog.capabilities:
            deny.append(PolicyFinding(rule="CAPABILITY_NOT_APPROVED", message=f"capability '{cap}' is not approved for automated CI generation"))

    # -- actions -----------------------------------------------------------
    for action in plan.get("actions", []) or []:
        uses = str(action.get("uses", ""))
        if not action.get("pinned") and not catalog.allow_unpinned:
            deny.append(PolicyFinding(rule="ACTION_NOT_PINNED", message=f"action '{uses}' is not pinned to an immutable version"))
        if not any(uses.startswith(prefix) for prefix in catalog.action_prefixes):
            deny.append(PolicyFinding(rule="ACTION_NOT_APPROVED", message=f"action '{uses}' is not in the approved action list"))

    # -- permissions --------------------------------------------------------
    permissions = plan.get("permissions", {}) or {}
    for scope, value in permissions.items():
        if value == "write":
            approvals.append(PolicyFinding(rule="PERMISSION_WRITE_REVIEW", message=f"permission '{scope}: write' requires review"))
        if value == "write" and scope in catalog.never_write:
            deny.append(PolicyFinding(rule="PERMISSION_NEVER_WRITE", message=f"permission '{scope}: write' is never granted by generated workflows"))
        if scope not in catalog.known_permissions:
            deny.append(PolicyFinding(rule="PERMISSION_UNKNOWN", message=f"unknown permission scope '{scope}'"))

    # -- licenses -------------------------------------------------------------
    for lic in plan.get("licenses", []) or []:
        if lic in catalog.denied_licenses:
            deny.append(PolicyFinding(rule="LICENSE_DENIED", message=f"dependency license '{lic}' is denied by organization policy"))

    # -- governance --------------------------------------------------------------
    if intent.get("target_branch") in catalog.protected_branches and intent.get("publish"):
        approvals.append(PolicyFinding(
            rule="PROTECTED_BRANCH",
            message=f"publishing to protected branch '{intent.get('target_branch')}'",
        ))
    if plan.get("has_deploy_job") and intent.get("deployment_target") == "production":
        approvals.append(PolicyFinding(rule="PRODUCTION_DEPLOY", message="plan includes a production deployment job"))
    if plan.get("removes_security"):
        approvals.append(PolicyFinding(rule="SECURITY_REMOVAL", message="plan removes or weakens a security control"))
    if plan.get("cloud_oidc"):
        approvals.append(PolicyFinding(rule="CLOUD_OIDC", message="plan requests cloud credentials via OIDC — verify the trust policy"))
    if risk.get("level") == "high":
        approvals.append(PolicyFinding(rule="HIGH_RISK", message="run classified as high risk"))
    if repo.get("is_fork"):
        approvals.append(PolicyFinding(rule="FORK_CONTEXT", message="change comes from a fork — review secrets usage"))

    if deny:
        decision = Decision.DENY
    elif approvals:
        decision = Decision.APPROVAL_REQUIRED
    else:
        decision = Decision.ALLOW
    return PolicyDecision(
        decision=decision, deny=deny, approval_reasons=approvals,
        evaluator="local", evaluated_at=utcnow(),
    )
