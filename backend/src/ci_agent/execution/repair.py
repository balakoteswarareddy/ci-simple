"""Bounded repair loop (Phase 6, PDF §5 step 10).

Validation failures feed back to the planner/refiner; the fix must pass the
same gates again. Attempts are bounded by policy (limits.max_repair_attempts)
and only low-risk deterministic-leaning patches apply — anything the patcher
rejects ends the loop with an explicit note.
"""
from __future__ import annotations

from pathlib import Path

from ..common.models import CandidatePlan, PipelineIR, PlannedAction, ValidationResult
from ..config import Settings
from ..llm.base import LLMCallStats, LLMClient
from ..observability.logging import get_logger
from ..observability.metrics import REPAIR_ATTEMPTS
from ..pipeline.patch import apply_repairs
from ..pipeline.render import RenderedOutput, render
from ..policy.catalog import PolicyCatalog
from ..validation.runner import all_passed, failures_text, ir_summary, run_all

LOG = get_logger("ci_agent.execution.repair")


async def refine_until_valid(
    ir: PipelineIR,
    rendered: RenderedOutput,
    results: list[ValidationResult],
    plan: CandidatePlan,
    settings: Settings,
    llm: LLMClient,
    catalog: PolicyCatalog,
    work_dir: Path,
    costs: list[dict],
) -> tuple[PipelineIR, RenderedOutput, list[ValidationResult], CandidatePlan, list[str], int]:
    max_attempts = min(settings.max_repair_attempts, catalog.max_repair_attempts)
    notes: list[str] = []
    attempts = 0
    while not all_passed(results) and attempts < max_attempts:
        attempts += 1
        failures = failures_text(results)
        summary = ir_summary(ir)
        try:
            repairs, stats = await llm.propose_repairs(failures, summary)
        except Exception as exc:
            notes.append(f"attempt {attempts}: refiner failed ({exc}) — trying deterministic rules")
            from ..llm.fallback import DeterministicClient

            repairs, stats = await DeterministicClient(settings).propose_repairs(failures, summary)
        costs.append({"model": stats.model, "input_tokens": stats.input_tokens,
                      "output_tokens": stats.output_tokens, "cost_usd_estimate": stats.cost_usd_estimate})
        if not repairs:
            notes.append(f"attempt {attempts}: no repairs proposed — stopping")
            REPAIR_ATTEMPTS.labels(outcome="none-proposed").inc()
            break
        ir, patch_notes = apply_repairs(ir, repairs, catalog)
        notes.extend(f"attempt {attempts}: {note}" for note in patch_notes)
        applied = sum(1 for n in patch_notes if "applied" in n or "updated" in n)
        if applied == 0:
            notes.append(f"attempt {attempts}: all repairs rejected by safety guards — stopping")
            REPAIR_ATTEMPTS.labels(outcome="rejected").inc()
            break
        # Re-derive the policy-relevant plan slice so validation can't drift
        # the IR away from what policy approved.
        plan = sync_plan_with_ir(ir, plan)
        rendered = render(ir)
        results = await run_all(ir, rendered, settings, work_dir)
        REPAIR_ATTEMPTS.labels(outcome="revalidated").inc()
        LOG.info("repair attempt %d applied=%d valid=%s", attempts, applied, all_passed(results))

    if attempts >= max_attempts and not all_passed(results):
        notes.append(f"repair budget exhausted ({max_attempts} attempts) — run will fail with findings attached")
        REPAIR_ATTEMPTS.labels(outcome="exhausted").inc()
    return ir, rendered, results, plan, notes, attempts


def sync_plan_with_ir(ir: PipelineIR, plan: CandidatePlan) -> CandidatePlan:
    """Rebuild the policy-relevant actions/permissions from (possibly
    repaired) IR so a follow-up policy check sees reality."""
    uses_steps = [s.uses for job in ir.jobs for s in job.steps if s.uses]
    actions: list[PlannedAction] = []
    for uses in dict.fromkeys(uses_steps):
        ref = uses.split("@", 1)[1] if "@" in uses else ""
        pinned = bool(ref) and ref not in ("main", "master", "latest")
        actions.append(PlannedAction(uses=uses, pinned=pinned, version=ref))
    updated = plan.model_copy(deep=True)
    updated.actions = actions
    updated.permissions = dict(ir.permissions)
    return updated
