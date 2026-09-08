"""Our generated GitHub workflows must be actionlint-clean (when the
binary is installed; otherwise the validator self-reports a skip).
"""
import shutil

import pytest

from ci_agent.common.models import (
    CandidatePlan,
    IRJob,
    IRStep,
    PipelineIR,
    PlannedAction,
    PlannedTool,
    PolicyDecision,
    RepositoryContext,
    RepoLanguage,
    UserIntent,
)
from ci_agent.knowledge.retrieve import Retrieval
from ci_agent.knowledge.store import KnowledgeStore
from ci_agent.pipeline.ir import build_ir
from ci_agent.pipeline.render import render
from ci_agent.validation.actionlint import run_actionlint


def test_generated_workflow_passes_actionlint(tmp_settings, tmp_path):
    if not shutil.which("actionlint"):
        pytest.skip("actionlint binary not installed")
    intent = UserIntent(platform="github", capabilities=["lint", "test"])
    plan = CandidatePlan(
        tools=[PlannedTool(name="ruff", version="0.4.0", capability="lint"),
               PlannedTool(name="shellcheck", version="0.9.0", capability="lint"),
               PlannedTool(name="pytest", version="8.2.0", capability="test")],
        actions=[PlannedAction(uses="actions/checkout@v4", pinned=True, version="v4"),
                 PlannedAction(uses="actions/setup-python@v5", pinned=True, version="v5")],
        permissions={"contents": "read"},
    )
    ctx = RepositoryContext(repo_url="https://x/y",
                            languages=[RepoLanguage(name="python", package_manager="pip")])
    ctx.context_hash = ctx.compute_hash()
    kstore = KnowledgeStore(tmp_settings)
    kstore.ensure_seeded()
    retrieval = Retrieval(records=[kstore.get("ruff"), kstore.get("shellcheck"), kstore.get("pytest")])
    ir = build_ir(intent, plan, ctx, retrieval, PolicyDecision(), tmp_settings, kstore)
    rendered = render(ir)
    path = tmp_path / rendered.filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered.content)
    result = run_actionlint(path, tmp_settings)
    assert result.provenance.get("runner") == "binary"
    assert result.passed, [e.message for e in result.errors]
