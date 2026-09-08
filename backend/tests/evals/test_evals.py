"""Agent evaluations (PDF §13): representative repos x requests with expected
decisions. Metrics: intent accuracy, unsupported-claim rate, policy
violations, invalid workflow rate. Uses the deterministic planner so evals
are hermetic (no model, no network).
"""
import json
from pathlib import Path

from ci_agent.agent.risks import classify_risk
from ci_agent.discovery.repo import LocalRepo, discover
from ci_agent.knowledge.retrieve import retrieve
from ci_agent.llm.fallback import DeterministicClient
from ci_agent.pipeline.ir import build_ir
from ci_agent.pipeline.render import render
from ci_agent.planner.intent import parse_intent
from ci_agent.planner.plan import build_plan
from ci_agent.policy.engine import build_policy_input
from ci_agent.policy.local import evaluate_local
from ci_agent.validation.schema_checks import check_ir, check_rendered
from ci_agent.validation.security_checks import check_workflow
from tests.conftest import FIXTURES

DATASET = json.loads((Path(__file__).parent / "dataset.json").read_text())


async def test_agent_evals(tmp_settings, kstore, catalog):
    assert DATASET, "empty eval dataset"
    rows = []
    for case in DATASET:
        repo = LocalRepo(path=(FIXTURES / case["repo"]).resolve(), commit_sha="fixture",
                         default_branch="", revision_requested="")
        ctx = discover(repo, f"https://github.com/acme/{case['repo']}")
        intent, _, _ = await parse_intent(case["request"], ctx, tmp_settings, DeterministicClient(tmp_settings))
        ret = retrieve(intent.capabilities, [l.name for l in ctx.languages], kstore, tmp_settings)
        plan = build_plan(intent, ctx, ret, catalog, tmp_settings, kstore)
        risk, _ = classify_risk(intent, plan, ctx, "", False, catalog.protected_branches)
        decision = evaluate_local(build_policy_input(intent, plan, ctx, risk.value, "", False), catalog)
        ir = build_ir(intent, plan, ctx, ret, decision, tmp_settings, kstore)
        rendered = render(ir)
        validity = all(r.passed for r in [
            check_ir(ir),
            check_rendered(rendered.content, ir.platform, rendered.filename),
            check_workflow(ir, rendered.content, catalog),
        ])
        known = set(kstore.all_tools())
        rows.append({
            "case": case["name"],
            "platform_ok": intent.platform == case["expected_platform"],
            "caps_ok": set(case["expected_capabilities"]) <= set(intent.capabilities),
            "tools_ok": set(case["expected_tools_subset"]) <= {t.name for t in plan.tools},
            "grounded": all(t.name in known for t in plan.tools),
            "no_prohibited": not (set(case["prohibited_absent"]) & {t.name for t in plan.tools}),
            "decision": decision.decision.value,
            "valid": validity,
        })

    print("\n" + "\n".join(
        f"{r['case']:18s} platform={r['platform_ok']} caps={r['caps_ok']} tools={r['tools_ok']} "
        f"grounded={r['grounded']} clean={r['no_prohibited']} policy={r['decision']} valid={r['valid']}"
        for r in rows
    ))
    assert all(r["platform_ok"] for r in rows), "platform accuracy"
    assert all(r["caps_ok"] for r in rows), "intent capability accuracy"
    assert all(r["tools_ok"] for r in rows), "expected tool selection"
    assert all(r["grounded"] for r in rows), "unsupported-claim rate must be 0"
    assert all(r["no_prohibited"] for r in rows), "prohibited tool leaked into plan"
    assert all(r["decision"] != "DENY" for r in rows), "policy violations"
    assert all(r["valid"] for r in rows), "invalid workflow rate must be 0"
