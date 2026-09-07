"""Local policy mirror + risk classification (mirrors OPA unit tests)."""
from ci_agent.agent.risks import classify_risk
from ci_agent.common.models import (
    CandidatePlan,
    PlannedAction,
    PlannedTool,
    RepositoryContext,
    RiskLevel,
    UserIntent,
)
from ci_agent.policy.engine import build_policy_input
from ci_agent.policy.local import evaluate_local

CTX = RepositoryContext(repo_url="https://github.com/o/r")


def _decide(catalog, intent_kwargs=None, plan_kwargs=None, risk="low", branch="feature/ci", publish=False):
    from ci_agent.policy.engine import build_policy_input

    intent_kwargs = {"platform": "github", "capabilities": ["lint", "test"], **(intent_kwargs or {})}
    intent = UserIntent(**intent_kwargs)
    plan_kwargs = {
        "tools": [PlannedTool(name="ruff", version="0.4.0", capability="lint")],
        "actions": [PlannedAction(uses="actions/checkout@v4", pinned=True)],
        "permissions": {"contents": "read"},
        **(plan_kwargs or {}),
    }
    plan = CandidatePlan(**plan_kwargs)
    return evaluate_local(build_policy_input(intent, plan, CTX, risk, branch, publish), catalog)


def test_allow_clean_plan(catalog):
    assert _decide(catalog).decision.value == "ALLOW"


def test_deny_unapproved_tool(catalog):
    d = _decide(catalog, plan_kwargs={"tools": [PlannedTool(name="evil-linter", version="1.0.0")]})
    assert d.decision.value == "DENY"
    assert d.deny[0].rule == "TOOL_NOT_APPROVED"


def test_deny_prohibited_tool(catalog):
    d = _decide(catalog, intent_kwargs={"prohibited_tools": ["ruff"]})
    assert d.decision.value == "DENY"
    assert any(f.rule == "TOOL_PROHIBITED" for f in d.deny)


def test_deny_unpinned_action(catalog):
    d = _decide(catalog, plan_kwargs={"actions": [PlannedAction(uses="actions/checkout@main", pinned=False)]})
    assert d.decision.value == "DENY"
    assert any(f.rule == "ACTION_NOT_PINNED" for f in d.deny)


def test_approval_protected_publish(catalog):
    d = _decide(catalog, branch="main", publish=True)
    assert d.decision.value == "APPROVAL_REQUIRED"


def test_no_approval_generate_only(catalog):
    assert _decide(catalog, branch="main", publish=False).decision.value == "ALLOW"


def test_approval_write_permission(catalog):
    d = _decide(catalog, plan_kwargs={"permissions": {"contents": "write"}})
    assert d.decision.value == "APPROVAL_REQUIRED"


def test_deny_license(catalog):
    d = _decide(catalog, plan_kwargs={"licenses": ["AGPL-3.0-only"]})
    assert d.decision.value == "DENY"


def test_deny_malformed(catalog):
    d = evaluate_local({"intent": {"capabilities": ["lint"]}, "plan": {}, "repo": {}, "risk": {}}, catalog)
    assert d.decision.value == "DENY"


def test_risk_levels(catalog):
    intent = UserIntent(platform="github", capabilities=["lint"])
    plan = CandidatePlan(permissions={"contents": "read"})
    level, _ = classify_risk(intent, plan, CTX, "", False, catalog.protected_branches)
    assert level == RiskLevel.LOW

    prod = UserIntent(platform="github", capabilities=["deploy"], deployment_target="production")
    pplan = CandidatePlan(permissions={"contents": "read"}, has_deploy_job=True)
    level, reasons = classify_risk(prod, pplan, CTX, "main", True, catalog.protected_branches)
    assert level == RiskLevel.HIGH
    assert reasons
