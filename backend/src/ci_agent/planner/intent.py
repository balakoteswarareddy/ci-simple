"""Intent parsing (PDF §5 step 5): LLM structured output with validation,
explicit deterministic fallback on any failure."""
from __future__ import annotations

from ..common.models import RepositoryContext, UserIntent
from ..common.util import truncate
from ..config import Settings
from ..llm.base import LLMCallStats, LLMClient
from ..observability.logging import get_logger
from ..policy.catalog import get_catalog
from ..security.redact import redact

LOG = get_logger("ci_agent.planner")

PLATFORM_ALIASES = {
    "github": "github", "gha": "github", "actions": "github",
    "azure": "azure", "ado": "azure",
    "gitlab": "gitlab", "gl": "gitlab",
    "jenkins": "jenkins",
}


class IntentError(ValueError):
    pass


def summarize_repo(ctx: RepositoryContext) -> str:
    """Small redacted fact block for the model — never raw file contents."""
    langs = ", ".join(
        f"{l.name} (manager={l.package_manager or '?'}, constraint={l.version_constraint or '?'})"
        for l in ctx.languages
    )
    tests = ", ".join(t.command or t.framework for t in ctx.test_setups)
    return redact(
        f"languages: {langs or 'unknown'}; "
        f"package_managers={ctx.package_managers}; "
        f"tests: {tests or 'none detected'}; "
        f"dockerfile={ctx.has_dockerfile}; "
        f"existing_ci={[c.path for c in ctx.existing_ci]}; "
        f"commit={ctx.commit_sha[:12]}"
    )


async def parse_intent(
    request_text: str,
    repo_ctx: RepositoryContext,
    settings: Settings,
    llm: LLMClient,
    extra_capabilities: list[str] | None = None,
) -> tuple[UserIntent, LLMCallStats, dict]:
    repo_facts = summarize_repo(repo_ctx)
    provenance: dict[str, str] = {"parser": llm.name}
    try:
        intent, stats = await llm.parse_intent(request_text, repo_facts)
    except Exception as exc:
        LOG.warning("llm intent parsing failed, using deterministic fallback err=%s", truncate(str(exc), 200))
        from ..llm.fallback import DeterministicClient

        intent, stats = await DeterministicClient(settings).parse_intent(request_text, repo_facts)
        provenance = {"parser": "deterministic", "fallback_reason": truncate(str(exc), 300)}

    # Normalize + validate against the approved catalog (fail fast, clear msg).
    catalog = get_catalog(settings)
    allowed_caps = {c.lower() for c in catalog.capabilities}
    platform = PLATFORM_ALIASES.get(intent.platform.strip().lower(), "")
    if not platform:
        raise IntentError(f"unsupported platform '{intent.platform}' (want github|azure|gitlab|jenkins)")

    caps: list[str] = []
    for raw in list(intent.capabilities) + list(extra_capabilities or []):
        c = raw.strip().lower().replace("_", "-")
        if c and c not in caps:
            caps.append(c)
    unknown = [c for c in caps if allowed_caps and c not in allowed_caps]
    if unknown:
        raise IntentError(
            f"unknown capabilities {unknown}; approved: {sorted(allowed_caps)}"
        )
    if not caps:
        raise IntentError("no capabilities requested or detected — describe what the CI should do")

    intent.platform = platform
    intent.capabilities = caps
    intent.prohibited_tools = sorted({t.strip().lower() for t in intent.prohibited_tools if t.strip()})
    intent.deployment_target = intent.deployment_target.strip().lower()
    LOG.info("parsed intent platform=%s caps=%s prohibited=%s", platform, caps, intent.prohibited_tools)
    return intent, stats, provenance
