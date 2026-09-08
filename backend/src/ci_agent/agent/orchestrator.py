"""Agent orchestrator (PDF §4 + §5): owns the workflow
inspect -> retrieve -> plan -> policy-check -> generate -> validate ->
refine -> approve -> publish, with evidence at every step.

The orchestrator is deterministic glue: it calls the LLM only through the
narrow client boundary and enforces policy/approval gates itself.
"""
from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager

from ..common.models import (
    ApprovalInput,
    ApprovalRecord,
    CandidatePlan,
    CostRecord,
    Decision,
    DecisionEvidence,
    PipelineIR,
    PolicyDecision,
    RepositoryContext,
    RiskLevel,
    RunOptions,
    RunStatus,
    UserIntent,
    ValidationResult,
)
from ..common.util import sha256_json, sha256_text, utcnow
from ..config import Settings
from ..discovery.repo import RepoAdapter, discover
from ..evidence.store import EvidenceStore
from ..execution.repair import refine_until_valid
from ..integrations import chainloop as chainloop_mod
from ..integrations import cosign as cosign_mod
from ..integrations import syft as syft_mod
from ..integrations.github import GitHubClient, GitHubError, merge_recommendation, parse_repo_url
from ..integrations.scanners import run_security_suite
from ..knowledge.retrieve import retrieve
from ..knowledge.store import KnowledgeStore
from ..llm.base import LLMCallStats, LLMClient, get_llm_client
from ..observability.logging import get_logger, set_run_id
from ..observability.metrics import (
    APPROVAL_WAIT,
    LLM_COST,
    LLM_TOKENS,
    RUN_DURATION,
    RUN_STEP_DURATION,
    RUNS_IN_PROGRESS,
    RUNS_TOTAL,
    TOOL_CALLS,
)
from ..pipeline import explain as explain_mod
from ..pipeline.ir import build_ir
from ..pipeline.render import RenderedOutput, render, supported_platforms
from ..planner.intent import IntentError, parse_intent
from ..planner.plan import build_plan
from ..policy.catalog import get_catalog
from ..policy.engine import PolicyError, build_policy_input, evaluate_policy
from ..security.redact import redact
from ..validation.runner import all_passed, run_all, skipped_validators
from .risks import classify_risk

LOG = get_logger("ci_agent.agent")


@contextmanager
def _timed(step: str):
    started = time.monotonic()
    try:
        yield
    finally:
        RUN_STEP_DURATION.labels(step=step).observe(time.monotonic() - started)


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        store: EvidenceStore | None = None,
        kstore: KnowledgeStore | None = None,
        llm: LLMClient | None = None,
    ):
        self.settings = settings
        self.store = store or EvidenceStore(settings)
        self.kstore = kstore or KnowledgeStore(settings)
        self.llm = llm or get_llm_client(settings)
        self.catalog = get_catalog(settings)

    # ------------------------------------------------------------ entry
    async def start_run(self, repo_url: str, request: str, options: RunOptions) -> str:
        if options.platform not in supported_platforms():
            raise ValueError(f"unsupported platform '{options.platform}'")
        run_id = self.store.create_run(repo_url, request, options)
        self.store.append_event(run_id, "run.queued", "info",
                                f"run queued for {options.platform}",
                                {"repo": redact(repo_url), "publish": options.publish})
        return run_id

    async def execute(self, run_id: str) -> None:
        set_run_id(run_id)
        started = time.monotonic()
        RUNS_IN_PROGRESS.inc()
        try:
            await self._execute_inner(run_id)
        except Exception as exc:  # noqa: BLE001 - orchestrator must never crash silently
            LOG.exception("run failed run=%s err=%s", run_id, exc)
            self._fail(run_id, f"{type(exc).__name__}: {redact(str(exc))[:500]}")
        finally:
            RUNS_IN_PROGRESS.dec()
            row = self.store.get_run(run_id) or {}
            platform = row.get("platform", "github")
            RUN_DURATION.labels(platform=platform).observe(time.monotonic() - started)
            RUNS_TOTAL.labels(platform=platform, status=row.get("status", "unknown")).inc()
            set_run_id("-")

    # ---------------------------------------------------------- pipeline
    async def _execute_inner(self, run_id: str) -> None:
        store = self.store
        row = store.get_run(run_id)
        if row is None:
            raise KeyError(f"unknown run {run_id}")
        options = RunOptions(**row["options"])
        costs: list[dict] = []
        store.update_run(run_id, status=RunStatus.RUNNING.value, current_step="init")
        store.append_event(run_id, "run.received", "info", "request received",
                           {"request": row["request"][:500], "platform": options.platform})

        # Step 2 — resolve repository + revision ------------------------------
        with _timed("repo.resolve"):
            repo_url = row["repo_url"]
            base_branch = options.base_branch
            is_github = repo_url.startswith("https://github.com/") or repo_url.startswith("github.com")
            enriched: dict = {}
            if is_github and self.settings.github_token:
                try:
                    client = GitHubClient(self.settings)
                    enriched = await client.get_repo(parse_repo_url(repo_url))
                    TOOL_CALLS.labels(tool="github:get_repo", status="ok").inc()
                except Exception as exc:
                    store.append_event(run_id, "repo.resolve", "warning",
                                       f"github enrichment failed: {exc}", {})
            elif is_github:
                store.append_event(run_id, "repo.resolve", "info",
                                   "no GITHUB_TOKEN — fork/default-branch detection skipped", {})
            if not base_branch:
                base_branch = enriched.get("default_branch", "") or "main"

        # Step 3 — checkout + discovery ----------------------------------------
        work_dir = self.settings.resolved_work_dir / run_id
        repo_path = work_dir / "repo"
        with _timed("repo.clone"):
            store.update_run(run_id, current_step="repo.clone")
            try:
                local = await asyncio.to_thread(
                    RepoAdapter(self.settings).prepare, repo_url, options.revision, repo_path)
            except Exception as exc:
                raise RuntimeError(f"repository preparation failed: {exc}") from exc
            store.append_event(run_id, "repo.clone", "info",
                               f"checked out {local.commit_sha[:12]}", {"sha": local.commit_sha})
        with _timed("repo.discover"):
            store.update_run(run_id, current_step="repo.discover")
            ctx = await asyncio.to_thread(discover, local, repo_url, self.settings)
            if enriched:
                ctx.default_branch = ctx.default_branch or enriched.get("default_branch", "")
                ctx.is_fork = bool(enriched.get("is_fork", False))
                ctx.context_hash = ctx.compute_hash()
            store.update_run(run_id, context=ctx.model_dump())
            store.append_event(run_id, "repo.discover", "info", explain_mod.describe_repo(ctx),
                               {"languages": [l.name for l in ctx.languages]})

        # Step 5 — structured intent --------------------------------------------
        with _timed("intent.parse"):
            store.update_run(run_id, current_step="intent.parse")
            try:
                intent, stats, provenance = await parse_intent(
                    row["request"], ctx, self.settings, self.llm, options.capabilities)
            except IntentError:
                raise
            self._record_llm(run_id, stats, costs, "intent")
            store.update_run(run_id, intent=intent.model_dump())
            store.append_event(run_id, "intent.parse", "info",
                               f"intent: {intent.platform} [{', '.join(intent.capabilities)}]",
                               {"provenance": provenance, "prohibited": intent.prohibited_tools})

        # Step 4 — knowledge retrieval -------------------------------------------
        with _timed("knowledge.retrieve"):
            store.update_run(run_id, current_step="knowledge.retrieve")
            self.kstore.ensure_seeded()
            ecosystems = [l.name for l in ctx.languages]
            retrieval = retrieve(intent.capabilities, ecosystems, self.kstore, self.settings)
            if retrieval.missing_capabilities:
                store.append_event(run_id, "knowledge.retrieve", "warning",
                                   f"no grounded tool for: {', '.join(retrieval.missing_capabilities)}", {})
            for note in retrieval.notes[:10]:
                store.append_event(run_id, "knowledge.retrieve", "info", note, {})

        # Plan -------------------------------------------------------------------
        with _timed("plan.build"):
            store.update_run(run_id, current_step="plan.build")
            plan = build_plan(intent, ctx, retrieval, self.catalog, self.settings, self.kstore)
            store.update_run(run_id, plan=plan.model_dump())
            store.append_event(run_id, "plan.build", "info",
                               f"plan: {len(plan.tools)} tools, {len(plan.actions)} actions",
                               {"tools": [t.name for t in plan.tools]})

        # Risk classification -------------------------------------------------------
        policy_target = base_branch if options.publish else ""
        risk, risk_reasons = classify_risk(
            intent, plan, ctx, policy_target, options.publish, self.catalog.protected_branches)
        store.update_run(run_id, risk_level=risk.value)
        store.append_event(run_id, "risk.classify", "info" if risk != RiskLevel.HIGH else "warning",
                           f"risk={risk.value}: {'; '.join(risk_reasons)}", {})

        # Step 6 — policy --------------------------------------------------------------
        with _timed("policy.evaluate"):
            store.update_run(run_id, current_step="policy.evaluate")
            try:
                policy = await evaluate_policy(
                    intent, plan, ctx, risk.value, policy_target, options.publish, self.settings)
            except PolicyError:
                raise
            store.update_run(run_id, policy=policy.model_dump())
            store.append_event(run_id, "policy.evaluate", "info" if policy.decision != Decision.DENY else "error",
                               f"policy: {policy.decision.value} via {policy.evaluator}",
                               {"deny": [f.rule for f in policy.deny],
                                "approvals": [f.rule for f in policy.approval_reasons]})
            if policy.decision == Decision.DENY:
                store.update_run(run_id, status=RunStatus.DENIED.value,
                                 error="denied by policy: " + "; ".join(f.message for f in policy.deny)[:500],
                                 costs=costs)
                self._finalize_evidence(run_id, "denied-by-policy")
                return

        # Step 7 — IR ---------------------------------------------------------------------
        with _timed("ir.build"):
            store.update_run(run_id, current_step="ir.build")
            ir = build_ir(intent, plan, ctx, retrieval, policy, self.settings, self.kstore)
            if options.workflow_filename:
                ir.metadata["workflow_filename"] = options.workflow_filename
            store.update_run(run_id, ir=ir.model_dump())

        # Step 8 — render -------------------------------------------------------------------
        with _timed("render"):
            store.update_run(run_id, current_step="render")
            rendered = render(ir)
            store.save_artifact(run_id, rendered.filename, rendered.content)
            store.update_run(run_id, rendered_yaml=rendered.content, renderer=rendered.renderer)
            for note in rendered.notes[:10]:
                store.append_event(run_id, "render", "info", note, {})

        # Step 9 — validate -------------------------------------------------------------------
        render_dir = work_dir / "render"
        with _timed("validate"):
            store.update_run(run_id, current_step="validate")
            results = await run_all(ir, rendered, self.settings, render_dir)
            for skipped in skipped_validators(results):
                store.append_event(run_id, "validate", "warning",
                                   f"validator '{skipped}' skipped (tool not installed)", {})

        # Step 10 — bounded repair + revalidation ------------------------------------------------
        if not all_passed(results):
            store.update_run(run_id, current_step="repair")
            ir, rendered, results, plan, repair_notes, attempts = await refine_until_valid(
                ir, rendered, results, plan, self.settings, self.llm,
                self.catalog, render_dir, costs)
            store.update_run(run_id, repair_attempts=attempts, ir=ir.model_dump(),
                             rendered_yaml=rendered.content,
                             validation=[r.model_dump() for r in results],
                             plan=plan.model_dump(), costs=costs)
            for note in repair_notes:
                store.append_event(run_id, "repair", "info", note, {})
            if attempts > 0:
                # Soundness: repaired IR must pass policy again.
                policy = await evaluate_policy(
                    intent, plan, ctx, risk.value, policy_target, options.publish, self.settings)
                store.update_run(run_id, policy=policy.model_dump())
                store.append_event(run_id, "policy.reevaluate", "info",
                                   f"post-repair policy: {policy.decision.value}", {})
                if policy.decision == Decision.DENY:
                    store.update_run(run_id, status=RunStatus.DENIED.value,
                                     error="denied by policy after repair", costs=costs)
                    self._finalize_evidence(run_id, "denied-by-policy-after-repair")
                    return
        else:
            store.update_run(run_id, validation=[r.model_dump() for r in results])

        if not all_passed(results):
            self._fail(run_id, "validation failed after bounded repair — findings attached")
            self._finalize_evidence(run_id, "failed-validation")
            return

        # Phase 3 — security suite (findings recorded, never block generation) ---------------------
        with _timed("security"):
            store.update_run(run_id, current_step="security")
            security = await asyncio.to_thread(
                run_security_suite, repo_path, intent.capabilities, self.settings)
            store.update_run(run_id, security=security)
            secret_count = len((security.get("secrets", {}) or {}).get("findings", []) or [])
            if secret_count:
                store.append_event(run_id, "security", "error",
                                   f"secret scan found {secret_count} finding(s) — review before publishing", {})

        # Phase 4 — supply chain --------------------------------------------------------------
        with _timed("supplychain"):
            store.update_run(run_id, current_step="supplychain")
            supply: dict = {}
            artifact_dir = store.artifact_dir(run_id)
            if "sbom" in intent.capabilities:
                sbom = await asyncio.to_thread(
                    syft_mod.generate_sbom, repo_path, artifact_dir / "sbom.cyclonedx.json", self.settings)
                supply["sbom"] = sbom.model_dump()
            if "sign" in intent.capabilities:
                target = artifact_dir / "sbom.cyclonedx.json"
                if not target.exists():
                    target = artifact_dir / rendered.filename
                sign = await asyncio.to_thread(cosign_mod.sign_blob, target, self.settings)
                supply["sign"] = sign.model_dump()
            supply["chainloop"] = {"status": "pending-finalize"}
            store.update_run(run_id, supply_chain=supply)

        # Explain + approval gate ------------------------------------------------------------------
        need_approval = (
            options.require_approval
            or self.settings.require_approval_default
            or (options.publish and (policy.decision == Decision.APPROVAL_REQUIRED or risk == RiskLevel.HIGH))
        )
        advisory = (policy.decision == Decision.APPROVAL_REQUIRED or risk == RiskLevel.HIGH) and not options.publish
        if advisory:
            store.append_event(run_id, "approval.gate", "warning",
                               "advisory: run would need approval before publishing (generate-only mode)", {})
        explanation = explain_mod.explain(
            intent, plan, policy, ir, results,
            approval_state="awaiting-approval" if need_approval else "not-required")
        store.update_run(run_id, explanation=explanation, costs=costs)

        if need_approval:
            store.update_run(run_id, status=RunStatus.AWAITING_APPROVAL.value, current_step="approval.gate")
            store.append_event(run_id, "approval.gate", "warning",
                               "paused for human approval before any mutation", {})
            self._finalize_evidence(run_id, "paused-for-approval")
            return

        # Phase 5 — publish --------------------------------------------------------------------------
        if options.publish:
            await self._publish(run_id, base_branch)

        self._finalize_evidence(run_id, "published" if options.publish else "generated")
        store.update_run(run_id, status=RunStatus.SUCCEEDED.value, current_step="done")
        store.append_event(run_id, "run.completed", "info", "run succeeded", {})

    # ------------------------------------------------------------- publish
    async def _publish(self, run_id: str, base_branch: str) -> None:
        store = self.store
        row = store.get_run(run_id)
        assert row is not None
        options = RunOptions(**row["options"])
        store.update_run(run_id, status=RunStatus.PUBLISHING.value, current_step="publish")
        repo_url = row["repo_url"]
        try:
            repo = parse_repo_url(repo_url)
        except GitHubError as exc:
            raise RuntimeError(f"publishing supports github repositories only: {exc}") from exc
        client = GitHubClient(self.settings)
        head_branch = options.target_branch or f"ci-agent/{run_id[:12]}"
        intent = UserIntent(**row["intent"])
        ir = PipelineIR(**row["ir"])
        policy = PolicyDecision(**row["policy"])
        results = [ValidationResult(**r) for r in row["validation"]]

        store.append_event(run_id, "publish", "info", f"publishing to branch '{head_branch}'", {})
        base_sha = await client.resolve_branch(repo, base_branch)
        await client.create_branch(repo, head_branch, base_sha)
        store.append_event(run_id, "publish", "info", f"created branch '{head_branch}' at {base_sha[:12]}", {})

        from ..pipeline.render import render as render_ir

        rendered_name = render_ir(ir).filename
        existing = await client.get_file(repo, rendered_name, base_branch)
        commit_msg = f"ci-agent: add {rendered_name} ({explain_mod.short_summary(intent, ir)[:100]})"
        commit_sha = await client.put_file(repo, rendered_name, row["rendered_yaml"],
                                           commit_msg, head_branch, (existing or {}).get("sha"))
        store.append_event(run_id, "publish", "info", f"committed {rendered_name} ({commit_sha[:12]})", {})

        evidence = store.get_evidence(run_id) or {}
        body = (row["explanation"] or "") + f"\n\n---\nEvidence: `{evidence.get('evidence_hash', 'pending')}` · run `{run_id}`"
        pr_title = options.pr_title or f"CI: add {rendered_name} ({intent.platform})"
        pr = await client.open_pr(repo, pr_title, head_branch, base_branch, body)
        store.append_event(run_id, "publish", "info", f"opened PR #{pr.get('number')}: {pr.get('url')}", pr)

        try:
            checks = await client.list_check_runs(repo, commit_sha)
        except Exception as exc:
            checks = []
            store.append_event(run_id, "publish", "warning", f"could not read check runs: {exc}", {})
        merge = merge_recommendation(checks, policy.decision.value, all_passed(results))
        store.update_run(run_id, publish={
            "head_branch": head_branch, "base_branch": base_branch, "commit_sha": commit_sha,
            "file": rendered_name, "pr": pr, "checks": checks, "merge": merge,
        })

    # ------------------------------------------------------------- approve
    async def decide(self, run_id: str, approval: ApprovalInput) -> dict:
        store = self.store
        set_run_id(run_id)
        try:
            row = store.get_run(run_id)
            if row is None:
                raise KeyError(f"unknown run {run_id}")
            if row["status"] != RunStatus.AWAITING_APPROVAL.value:
                raise ValueError(f"run is {row['status']}, not awaiting approval")
            record = ApprovalRecord(run_id=run_id, approver=approval.approver,
                                    decision=approval.decision, reason=approval.reason)
            store.save_approval(record)
            try:
                from datetime import datetime, timezone

                waited = (utcnow() - datetime.fromisoformat(row["updated_at"])).total_seconds()
                APPROVAL_WAIT.observe(max(waited, 0))
            except Exception:
                pass
            store.append_event(run_id, "approval.decision", "info",
                               f"{approval.decision} by {approval.approver}: {approval.reason[:200]}",
                               {"approver": approval.approver, "decision": approval.decision})
            if approval.decision == "reject":
                store.update_run(run_id, status=RunStatus.CANCELLED.value, current_step="done")
                self._finalize_evidence(run_id, f"rejected-by-{approval.approver}")
                return {"status": "cancelled"}
            options = RunOptions(**row["options"])
            if options.publish:
                base = (row.get("publish") or {}).get("base_branch") or "main"
                # Re-derive base from stored context when publish block is empty.
                ctx = RepositoryContext(**row["context"]) if row.get("context") else None
                base_branch = options.base_branch or (ctx.default_branch if ctx else "") or base
                try:
                    await self._publish(run_id, base_branch)
                except Exception as exc:
                    self._fail(run_id, f"publish failed: {redact(str(exc))[:500]}")
                    self._finalize_evidence(run_id, "failed-publish")
                    return {"status": "failed"}
                self._finalize_evidence(run_id, "published-after-approval")
            else:
                self._finalize_evidence(run_id, "approved-generate-only")
            store.update_run(run_id, status=RunStatus.SUCCEEDED.value, current_step="done")
            store.append_event(run_id, "run.completed", "info", "run succeeded after approval", {})
            return {"status": "succeeded"}
        finally:
            set_run_id("-")

    # ------------------------------------------------------------- helpers
    def _record_llm(self, run_id: str, stats: LLMCallStats, costs: list[dict], where: str) -> None:
        costs.append({"model": stats.model, "input_tokens": stats.input_tokens,
                      "output_tokens": stats.output_tokens, "cost_usd_estimate": stats.cost_usd_estimate})
        if stats.input_tokens or stats.output_tokens:
            LLM_TOKENS.labels(model=stats.model, direction="input").inc(stats.input_tokens)
            LLM_TOKENS.labels(model=stats.model, direction="output").inc(stats.output_tokens)
            LLM_COST.labels(model=stats.model).inc(stats.cost_usd_estimate)
        self.store.append_event(run_id, f"llm.{where}", "info",
                                f"model={stats.model} tokens={stats.input_tokens}+{stats.output_tokens}",
                                {"model": stats.model})

    def _fail(self, run_id: str, error: str) -> None:
        try:
            self.store.update_run(run_id, status=RunStatus.FAILED.value, error=error, current_step="failed")
            self.store.append_event(run_id, "run.failed", "error", error, {})
        except Exception:
            LOG.exception("failed to record failure for run=%s", run_id)

    def _finalize_evidence(self, run_id: str, final_action: str) -> dict:
        """Assemble + persist the immutable decision record (§11), then push
        the attestation envelope to Chainloop when configured."""
        store = self.store
        row = store.get_run(run_id) or {}
        intent = UserIntent(**row.get("intent", {})) if row.get("intent") else None
        plan = CandidatePlan(**row.get("plan", {})) if row.get("plan") else CandidatePlan()
        policy = PolicyDecision(**row.get("policy", {})) if row.get("policy") else None
        ctx = RepositoryContext(**row.get("context", {})) if row.get("context") else None
        results = [ValidationResult(**r) for r in (row.get("validation") or [])]
        approval_raw = store.get_approval(run_id)
        approval = ApprovalRecord(**approval_raw) if approval_raw else None

        knowledge_refs: list[str] = []
        for tool in plan.tools:
            knowledge_refs.extend(tool.knowledge_refs)
        artifact_hashes = {
            "workflow": "sha256:" + sha256_text(row.get("rendered_yaml", "")),
            "ir": "sha256:" + sha256_json(row.get("ir", {})),
            "plan": plan.compute_hash(),
        }
        supply = row.get("supply_chain") or {}
        if (supply.get("sbom") or {}).get("digest"):
            artifact_hashes["sbom"] = supply["sbom"]["digest"]

        evidence = DecisionEvidence(
            run_id=run_id,
            request=(row.get("request") or "")[:2000],
            repo_url=row.get("repo_url", ""),
            repo_revision=row.get("revision", ""),
            commit_sha=ctx.commit_sha if ctx else "",
            context_hash=ctx.context_hash if ctx else "",
            knowledge_refs=sorted(set(knowledge_refs)),
            model=intent.planner if intent else "",
            plan_hash=plan.compute_hash(),
            policy=policy,
            risk_level=row.get("risk_level", "low"),
            artifact_hashes=artifact_hashes,
            validator_outputs=results,
            approval=approval,
            final_action=final_action,
            costs=[CostRecord(**c) for c in (row.get("costs") or [])],
        )
        evidence.evidence_hash = "sha256:" + evidence.compute_hash()
        version = store.save_evidence(evidence)
        store.append_event(run_id, "evidence.finalize", "info",
                           f"evidence v{version} hash={evidence.evidence_hash[:20]} action={final_action}", {})

        # Chainloop attestation (best effort; local evidence is authoritative).
        try:
            client = chainloop_mod.ChainloopClient(self.settings)
            envelope = client.build_envelope(evidence.model_dump(), artifact_hashes)
            supply["chainloop"] = client.push_attestation_sync(envelope)
            store.update_run(run_id, supply_chain=supply)
        except Exception as exc:
            LOG.warning("chainloop push failed: %s", exc)
        return evidence.model_dump()
