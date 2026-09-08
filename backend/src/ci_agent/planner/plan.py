"""Candidate plan builder (PDF §5): intent + repo facts + knowledge ->
grounded tool/action selection. The planner NEVER invents tools: anything
without a knowledge record is omitted with an explicit note (§15)."""
from __future__ import annotations

from ..common.models import CandidatePlan, PlannedAction, PlannedTool, RepositoryContext, UserIntent
from ..config import Settings
from ..knowledge.retrieve import Retrieval
from ..knowledge.store import KnowledgeStore
from ..observability.logging import get_logger
from ..pipeline.actions import SETUP_ACTIONS, action_ref, is_approved_action
from ..policy.catalog import PolicyCatalog

LOG = get_logger("ci_agent.planner")

SECURITY_CAPS = {"sast", "sca", "secrets", "container-scan", "iac-scan"}

#: auxiliary file linters added to every lint job when grounded + relevant.
AUX_LINT_TOOLS: list[tuple[str, str]] = [
    ("yamllint", "always"),
    ("shellcheck", "always"),      # guarded by hashFiles condition in IR
    ("actionlint", "github-only"),
    ("hadolint", "dockerfile-only"),
]


def build_plan(
    intent: UserIntent,
    repo_ctx: RepositoryContext,
    retrieval: Retrieval,
    catalog: PolicyCatalog,
    settings: Settings,
    store: KnowledgeStore,
) -> CandidatePlan:
    ecosystems = [l.name for l in repo_ctx.languages] or ["any"]
    prohibited = {t.lower() for t in intent.prohibited_tools}
    notes: list[str] = list(retrieval.notes)
    tools: dict[str, PlannedTool] = {}

    for cap in intent.capabilities:
        cands = [
            r for r in retrieval.records
            if cap in [c.lower() for c in r.capabilities]
        ]
        if cap == "lint":
            cands += _aux_lint_candidates(intent, repo_ctx, prohibited, store, notes)
        chosen = next((r for r in cands if r.tool.lower() not in prohibited), None)
        if chosen is None:
            if any(r.tool.lower() in prohibited for r in cands):
                notes.append(f"capability '{cap}': candidate tools prohibited by request — omitted")
            else:
                notes.append(f"capability '{cap}': no grounded tool available — omitted (never invented)")
            continue
        if chosen.tool in tools:
            continue
        version = chosen.versions[0] if chosen.versions else "unknown"
        source_url = chosen.source.url if chosen.source else ""
        tools[chosen.tool] = PlannedTool(
            name=chosen.tool,
            version=version,
            capability=cap,
            reason=f"ranked for '{cap}' on {ecosystems} (source: {source_url or 'catalog'})",
            knowledge_refs=[source_url] if source_url else [],
        )
        # extra grounded lint tools join the same job (dedup by name below).
        if cap == "lint":
            for extra in cands[1:]:
                if extra.tool in tools or extra.tool.lower() in prohibited:
                    continue
                tools[extra.tool] = PlannedTool(
                    name=extra.tool,
                    version=extra.versions[0] if extra.versions else "unknown",
                    capability=cap,
                    reason=f"auxiliary file linter for '{cap}'",
                    knowledge_refs=[extra.source.url] if extra.source else [],
                )

    actions = _select_actions(intent, repo_ctx, catalog, notes, tools, store)

    permissions: dict[str, str] = {"contents": "read"}
    if "sign" in intent.capabilities:
        permissions["attestations"] = "write"
        permissions["id-token"] = "write"
    cloud_oidc = bool(intent.deployment_target)
    if cloud_oidc:
        permissions["id-token"] = "write"

    plan = CandidatePlan(
        tools=list(tools.values()),
        actions=actions,
        permissions=permissions,
        licenses=list(repo_ctx.licenses),
        has_deploy_job="deploy" in intent.capabilities,
        touches_security=any(c in SECURITY_CAPS for c in intent.capabilities),
        removes_security=False,
        cloud_oidc=cloud_oidc,
        notes=notes,
    )
    LOG.info("built plan tools=%s actions=%d", [t.name for t in plan.tools], len(actions))
    return plan


def _aux_lint_candidates(intent, repo_ctx, prohibited, store, notes):
    out = []
    for tool_name, when in AUX_LINT_TOOLS:
        if when == "github-only" and intent.platform != "github":
            continue
        if when == "dockerfile-only" and not repo_ctx.has_dockerfile:
            continue
        if tool_name.lower() in prohibited:
            continue
        record = store.get(tool_name)
        if record is None:
            notes.append(f"auxiliary linter '{tool_name}' has no knowledge record — skipped")
            continue
        out.append(record)
    return out


def _select_actions(intent, repo_ctx, catalog, notes, tools, store) -> list[PlannedAction]:
    """Select every action the IR may emit. Policy evaluates this exact list,
    so the renderer must never introduce a `uses:` that is not here."""
    actions: list[PlannedAction] = []

    def add(name: str) -> None:
        if name in [a.uses.split("@")[0] for a in actions]:
            return
        try:
            ref = action_ref(name)
        except KeyError:
            notes.append(f"action '{name}' has no pinned version — skipped")
            return
        if not is_approved_action(ref, catalog.action_prefixes):
            notes.append(f"action '{ref}' is not in the approved catalog — skipped")
            return
        actions.append(PlannedAction(uses=ref, pinned=True, version=ref.split("@")[1]))

    if intent.platform == "github":
        add("actions/checkout")
        for lang in repo_ctx.languages:
            if lang.name in SETUP_ACTIONS:
                add(SETUP_ACTIONS[lang.name]["action"])
        if "docker-build" in intent.capabilities or (
            repo_ctx.has_dockerfile and "container-scan" in intent.capabilities
        ):
            add("docker/setup-buildx-action")
            add("docker/build-push-action")
        # Official action-installs for selected tools (trivy-action, ...).
        for tool in tools.values():
            record = store.get(tool.name)
            if record is None:
                continue
            for method in record.install_methods:
                if method.type == "action":
                    add(method.command.strip().split("@")[0])
        # Artifact upload for SBOM/signing evidence.
        if {"sbom", "sign"} & set(intent.capabilities):
            add("actions/upload-artifact")
    else:
        notes.append(f"platform '{intent.platform}' uses native tasks — no github actions selected")
    return actions
