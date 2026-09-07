"""Golden determinism tests (PDF §13): fixed repo snapshot + fixed intent +
fixed knowledge snapshot -> byte-identical IR and rendered pipelines.

To regenerate after an INTENTIONAL change, run:
    python backend/tests/golden/regen.py
and review the diff before committing.
"""
import json
from pathlib import Path

from ci_agent.common import db as db_module
from ci_agent.config import Settings
from ci_agent.discovery.repo import LocalRepo, discover
from ci_agent.knowledge.store import KnowledgeStore
from ci_agent.knowledge.retrieve import retrieve
from ci_agent.llm.fallback import DeterministicClient
from ci_agent.pipeline.ir import build_ir
from ci_agent.pipeline.render import render
from ci_agent.planner.intent import parse_intent
from ci_agent.planner.plan import build_plan
from ci_agent.policy.catalog import get_catalog, reset_catalog_cache
from ci_agent.policy.engine import build_policy_input
from ci_agent.policy.local import evaluate_local
from tests.conftest import FIXTURES, OPA_STORE

GOLDEN = Path(__file__).parent
CASES = sorted((GOLDEN / "cases").glob("*.json"))


def _settings_for(db_path: Path) -> Settings:
    return Settings(
        DATABASE_URL=f"sqlite:///{db_path}",
        OPA_BUNDLE_DIR=str(OPA_STORE),
        ALLOW_LOCAL_REPOS=True,
    )


async def _build(case: dict, db_path: Path):
    db_module.reset_engine()
    reset_catalog_cache()
    settings = _settings_for(db_path)
    try:
        kstore = KnowledgeStore(settings)
        snapshot = json.loads((GOLDEN / case["snapshot"]).read_text())
        kstore.load_snapshot(snapshot)
        repo = LocalRepo(path=(FIXTURES / case["repo"]).resolve(), commit_sha="fixture",
                         default_branch="", revision_requested="")
        ctx = discover(repo, f"https://github.com/acme/{case['repo']}")
        llm = DeterministicClient(settings)
        intent, _, _ = await parse_intent(case["request"], ctx, settings, llm)
        ret = retrieve(intent.capabilities, [l.name for l in ctx.languages], kstore, settings)
        catalog = get_catalog(settings)
        plan = build_plan(intent, ctx, ret, catalog, settings, kstore)
        decision = evaluate_local(build_policy_input(intent, plan, ctx, "low", "", False), catalog)
        assert decision.decision.value == "ALLOW"
        ir = build_ir(intent, plan, ctx, ret, decision, settings, kstore)
        return ir
    finally:
        db_module.reset_engine()
        reset_catalog_cache()


async def test_golden_cases(tmp_path):
    assert CASES, "no golden cases found"
    for case_file in CASES:
        case = json.loads(case_file.read_text())
        ir = await _build(case, tmp_path / f"{case['name']}.db")
        expected_ir = (GOLDEN / "expected" / case["expected_ir"]).read_text()
        actual_ir = json.dumps(ir.model_dump(), indent=2, sort_keys=True, default=str)
        assert actual_ir == expected_ir, f"IR drift in case {case['name']}"
        for platform, fname in case["expected_renders"].items():
            ir.platform = platform
            expected = (GOLDEN / "expected" / fname).read_text()
            actual = render(ir).content
            assert actual == expected, f"render drift in case {case['name']} platform {platform}"
