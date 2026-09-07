"""Regenerate golden snapshot + expected outputs.

Usage:  python backend/tests/golden/regen.py
Review the git diff carefully — golden changes must be intentional.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ci_agent.common import db as db_module  # noqa: E402
from ci_agent.config import Settings  # noqa: E402
from ci_agent.discovery.repo import LocalRepo, discover  # noqa: E402
from ci_agent.knowledge.retrieve import retrieve  # noqa: E402
from ci_agent.knowledge.seeds import load_seed_records  # noqa: E402
from ci_agent.knowledge.store import KnowledgeStore  # noqa: E402
from ci_agent.llm.fallback import DeterministicClient  # noqa: E402
from ci_agent.pipeline.ir import build_ir  # noqa: E402
from ci_agent.pipeline.render import render  # noqa: E402
from ci_agent.planner.intent import parse_intent  # noqa: E402
from ci_agent.planner.plan import build_plan  # noqa: E402
from ci_agent.policy.catalog import get_catalog, reset_catalog_cache  # noqa: E402
from ci_agent.policy.engine import build_policy_input  # noqa: E402
from ci_agent.policy.local import evaluate_local  # noqa: E402

GOLDEN = Path(__file__).parent
REPO_ROOT = GOLDEN.parents[2]
FIXTURES = REPO_ROOT / "backend" / "tests" / "fixtures" / "repos"
OPA_STORE = REPO_ROOT / "deploy" / "opa" / "store"
FIXED_TS = datetime(2025, 6, 1, tzinfo=timezone.utc)

WANT = {"ruff", "flake8", "actionlint", "yamllint", "shellcheck", "hadolint", "pytest",
        "bandit", "semgrep", "pip-audit", "osv-scanner", "gitleaks", "trufflehog", "eslint", "jest"}


async def build_case(case_file: Path) -> None:
    case = json.loads(case_file.read_text())
    db_path = Path(f"/tmp/golden-{case['name']}.db")
    if db_path.exists():
        db_path.unlink()
    db_module.reset_engine()
    reset_catalog_cache()
    settings = Settings(DATABASE_URL=f"sqlite:///{db_path}",
                        OPA_BUNDLE_DIR=str(OPA_STORE), ALLOW_LOCAL_REPOS=True)
    try:
        kstore = KnowledgeStore(settings)
        kstore.load_snapshot(json.loads((GOLDEN / case["snapshot"]).read_text()))
        repo = LocalRepo(path=(FIXTURES / case["repo"]).resolve(), commit_sha="fixture",
                         default_branch="", revision_requested="")
        ctx = discover(repo, f"https://github.com/acme/{case['repo']}")
        intent, _, _ = await parse_intent(case["request"], ctx, settings, DeterministicClient(settings))
        ret = retrieve(intent.capabilities, [l.name for l in ctx.languages], kstore, settings)
        catalog = get_catalog(settings)
        plan = build_plan(intent, ctx, ret, catalog, settings, kstore)
        decision = evaluate_local(build_policy_input(intent, plan, ctx, "low", "", False), catalog)
        assert decision.decision.value == "ALLOW", decision
        ir = build_ir(intent, plan, ctx, ret, decision, settings, kstore)
        (GOLDEN / "expected" / case["expected_ir"]).write_text(
            json.dumps(ir.model_dump(), indent=2, sort_keys=True, default=str))
        for platform, fname in case["expected_renders"].items():
            ir.platform = platform
            (GOLDEN / "expected" / fname).write_text(render(ir).content)
        print(f"{case['name']}: intent={intent.capabilities} tools={[t.name for t in plan.tools]}")
    finally:
        db_module.reset_engine()
        reset_catalog_cache()


async def main() -> None:
    snap = []
    for record in load_seed_records():
        if record.tool in WANT:
            record.source.source_type = "snapshot"
            record.source.retrieved_at = FIXED_TS
            record.record_hash = record.compute_hash()
            snap.append(record.model_dump())
    (GOLDEN / "snapshot.json").write_text(json.dumps(snap, indent=2, sort_keys=True, default=str))
    for case_file in sorted((GOLDEN / "cases").glob("*.json")):
        await build_case(case_file)
    print("golden regenerated — review the diff!")


if __name__ == "__main__":
    asyncio.run(main())
