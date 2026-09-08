"""OPA server parity: when an OPA server is reachable, its decisions must
match the local mirror (rule-for-rule). Skipped in environments without OPA.
"""
import os

import httpx
import pytest

from ci_agent.policy.catalog import get_catalog
from ci_agent.policy.engine import build_policy_input
from ci_agent.policy.local import evaluate_local
from ci_agent.policy.opa import OPAClient
from ci_agent.common.models import (
    CandidatePlan,
    PlannedAction,
    PlannedTool,
    RepositoryContext,
    UserIntent,
)

OPA_URL = os.environ.get("OPA_URL", "http://localhost:8181")


def _case(tools, actions, permissions, caps, prohibited=None, publish=False, branch="feature/x"):
    intent = UserIntent(platform="github", capabilities=caps, prohibited_tools=prohibited or [])
    plan = CandidatePlan(
        tools=[PlannedTool(name=n, version=v, capability="lint") for n, v in tools],
        actions=[PlannedAction(uses=u, pinned=p) for u, p in actions],
        permissions=permissions,
    )
    repo = RepositoryContext(repo_url="https://github.com/o/r")
    return intent, plan, repo, publish, branch


CASES = [
    _case([("ruff", "0.4.0")], [("actions/checkout@v4", True)], {"contents": "read"}, ["lint"]),
    _case([("evil-tool", "1.0")], [("actions/checkout@v4", True)], {"contents": "read"}, ["lint"]),
    _case([("ruff", "0.4.0")], [("actions/checkout@v4", True)], {"contents": "write"}, ["lint"]),
    _case([("ruff", "unknown")], [("actions/checkout@v4", True)], {"contents": "read"}, ["lint"]),
]


async def _reachable() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{OPA_URL}/health")
        return response.status_code == 200
    except Exception:
        return False


async def test_opa_matches_local_mirror(tmp_settings):
    if not await _reachable():
        pytest.skip("no OPA server reachable (set OPA_URL or run compose)")
    from ci_agent.config import Settings

    settings = Settings(OPA_URL=OPA_URL, OPA_BUNDLE_DIR=tmp_settings.opa_bundle_dir)
    client = OPAClient(settings)
    catalog = get_catalog(tmp_settings)
    for intent, plan, repo, publish, branch in CASES:
        opa_input = build_policy_input(intent, plan, repo, "low", branch, publish)
        server = await client.evaluate(opa_input)
        mirror = evaluate_local(opa_input, catalog)
        assert server.decision == mirror.decision, opa_input
        assert {f.rule for f in server.deny} == {f.rule for f in mirror.deny}
        assert {f.rule for f in server.approval_reasons} == {f.rule for f in mirror.approval_reasons}
