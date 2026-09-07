"""Pipeline IR builder (PDF §4: the most important design decision).

Deterministic, testable, platform-neutral. Converts the approved candidate
plan into versioned PipelineIR. Renderers consume IR only — the LLM never
touches this step.
"""
from __future__ import annotations

import re

from ..common.models import (
    CandidatePlan,
    IRGate,
    IRJob,
    IRStep,
    PipelineIR,
    PolicyDecision,
    RepositoryContext,
    UserIntent,
)
from ..common.util import new_id
from ..config import Settings
from ..knowledge.retrieve import Retrieval
from ..knowledge.store import KnowledgeStore
from ..observability.logging import get_logger
from .actions import SETUP_ACTIONS, action_ref
from .commands import FALLBACK_INSTALL, command_for, condition_for

LOG = get_logger("ci_agent.pipeline")

#: capability -> job bucket (fixed order = needs chain order)
JOB_ORDER = ["lint", "test", "security", "iac", "container", "deploy"]
CAP_TO_JOB = {
    "lint": "lint", "format": "lint",
    "test": "test",
    "sast": "security", "sca": "security", "secrets": "security",
    "iac-scan": "iac",
    "container-scan": "container", "docker-build": "container", "sbom": "container", "sign": "container",
    "build": "container",
    "deploy": "deploy",
}

PKG_INSTALL_TYPES = {"pip", "npm", "go", "cargo", "gem", "composer", "apt"}
EVIDENCE_BY_CAP = {
    "sbom": ["sbom-cyclonedx"],
    "sign": ["signature", "certificate"],
    "sast": ["sast-report"],
    "sca": ["sca-report"],
    "deploy": ["deployment-record"],
}


def build_ir(
    intent: UserIntent,
    plan: CandidatePlan,
    repo_ctx: RepositoryContext,
    retrieval: Retrieval,
    policy: PolicyDecision,
    settings: Settings,
    store: KnowledgeStore,
) -> PipelineIR:
    ecosystems = [l.name for l in repo_ctx.languages]
    records = {r.tool: r for r in retrieval.records}
    for tool in plan.tools:
        if tool.name not in records:
            record = store.get(tool.name)
            if record is not None:
                records[tool.name] = record

    buckets: dict[str, list] = {job: [] for job in JOB_ORDER}
    for tool in plan.tools:
        buckets[CAP_TO_JOB.get(tool.capability, "test")].append(tool)

    jobs: list[IRJob] = []
    prev_job_id: str | None = None
    for job_key in JOB_ORDER:
        tools = buckets[job_key]
        if job_key == "deploy" and not plan.has_deploy_job:
            continue
        if not tools and job_key != "deploy":
            continue
        job = _build_job(job_key, tools, intent, plan, repo_ctx, ecosystems, records, prev_job_id)
        jobs.append(job)
        prev_job_id = job.id

    branches = intent.trigger_branches or [repo_ctx.default_branch or "main"]
    gates = [
        IRGate(id="policy", type="policy", config={
            "decision": policy.decision.value,
            "evaluator": policy.evaluator,
            "deny": [f.rule for f in policy.deny],
            "approvals": [f.rule for f in policy.approval_reasons],
        })
    ]
    if policy.decision.value == "APPROVAL_REQUIRED":
        gates.append(IRGate(id="human-approval", type="approval", config={
            "reasons": [f.message for f in policy.approval_reasons],
        }))

    evidence_reqs: list[str] = []
    for cap in intent.capabilities:
        evidence_reqs += EVIDENCE_BY_CAP.get(cap, [])

    ir = PipelineIR(
        version="1.0",
        platform=intent.platform,
        name="ci",
        triggers={"push": {"branches": branches}, "pull_request": {"branches": branches}},
        jobs=jobs,
        permissions=dict(plan.permissions),
        gates=gates,
        evidence_requirements=sorted(set(evidence_reqs)),
        metadata={
            "generator": "ci-agent",
            "plan_hash": plan.compute_hash(),
            "context_hash": repo_ctx.context_hash,
            "notes": plan.notes,
        },
    )
    LOG.info("built IR jobs=%s steps=%d", [j.id for j in jobs], sum(len(j.steps) for j in jobs))
    return ir


# -- job assembly -------------------------------------------------------
def _build_job(job_key, tools, intent, plan, repo_ctx, ecosystems, records, needs_prev):
    job_id = job_key
    needs = [needs_prev] if needs_prev else []
    steps: list[IRStep] = []
    seq = 0

    def add(step: IRStep) -> None:
        nonlocal seq
        seq += 1
        if not step.id:
            step.id = f"{job_id}-s{seq}"
        steps.append(step)

    if intent.platform == "github":
        checkout = next((a for a in plan.actions if a.uses.startswith("actions/checkout@")), None)
        if checkout:
            with_args: dict = {}
            if any(t.name in ("gitleaks", "trufflehog") for t in tools):
                with_args["fetch-depth"] = "0"
            add(IRStep(id="", name="Checkout", uses=checkout.uses, with_args=with_args))

    for eco in ecosystems:
        setup = SETUP_ACTIONS.get(eco)
        if setup is None:
            continue
        version = _runtime_version(eco, repo_ctx, setup["default"])
        uses = ""
        if intent.platform == "github":
            try:
                uses = action_ref(setup["action"])
            except KeyError:
                uses = ""
        add(IRStep(
            id="", name=f"Set up {eco}",
            tool="setup",
            uses=uses,
            with_args={"ecosystem": eco, "version": version, setup["kwarg"]: version},
        ))

    if job_key in ("test", "security"):
        for command in _deps_install_commands(repo_ctx):
            add(IRStep(id="", name="Install dependencies", run=command))

    if job_key == "deploy":
        target = intent.deployment_target or "staging"
        add(IRStep(
            id="", name=f"Deploy to {target}",
            capability="deploy",
            run=f'echo "deploy step for {target}: configure deployment commands after review"',
            env={"DEPLOY_TARGET": target},
        ))
        return IRJob(id=job_id, name=f"Deploy ({target})", needs=needs,
                     permissions=dict(plan.permissions), steps=steps, environment=target)

    for tool in tools:
        record = records.get(tool.name)
        for step in _tool_steps(tool.name, tool.capability, record, intent.platform, repo_ctx):
            add(step)

    if job_key == "container" and intent.platform == "github":
        if any(t.capability in ("sbom", "sign") for t in tools):
            upload = next((a for a in plan.actions if a.uses.startswith("actions/upload-artifact@")), None)
            if upload:
                add(IRStep(id="", name="Upload SBOM artifacts", uses=upload.uses,
                           with_args={"name": "sbom", "path": "sbom.cyclonedx.json\nsbom.sig\nsbom.pem"},
                           condition="always()"))

    artifacts = []
    if job_key == "container" and any(t.capability in ("sbom", "sign") for t in tools):
        artifacts = ["sbom.cyclonedx.json", "sbom.sig", "sbom.pem"]
    return IRJob(id=job_id, name=job_key.capitalize(), needs=needs,
                 permissions=dict(plan.permissions), steps=steps, artifacts=artifacts)


def _deps_install_commands(repo_ctx: RepositoryContext) -> list[str]:
    """Project dependency install per ecosystem, derived from discovery.

    Test and SCA steps are meaningless without the project's own deps
    installed (pip-audit scans the environment, pytest imports the code).
    """
    dep_files = list(repo_ctx.dependency_files)
    locks = set(repo_ctx.lockfiles)
    commands: list[str] = []
    seen_managers: set[str] = set()
    for lang in repo_ctx.languages:
        pm = lang.package_manager
        if not pm or pm in seen_managers:
            continue
        seen_managers.add(pm)
        if pm == "pip":
            req = next((f for f in dep_files if re.search(r"requirements.*\.txt$", f)), "")
            if req:
                commands.append(f"pip install -r {req}")
            elif any(f.endswith(("pyproject.toml", "setup.py")) for f in dep_files):
                commands.append("pip install -e .")
        elif pm == "poetry":
            commands.append("poetry install")
        elif pm == "pipenv":
            commands.append("pipenv install --dev")
        elif pm == "pdm":
            commands.append("pdm install")
        elif pm == "npm":
            commands.append("npm ci" if any("package-lock.json" in l for l in locks) else "npm install")
        elif pm == "yarn":
            commands.append("yarn install --frozen-lockfile" if any("yarn.lock" in l for l in locks) else "yarn install")
        elif pm == "pnpm":
            commands.append("pnpm install --frozen-lockfile" if any("pnpm-lock.yaml" in l for l in locks) else "pnpm install")
        elif pm == "go":
            commands.append("go mod download")
        elif pm == "bundler":
            commands.append("bundle install")
        elif pm == "composer":
            commands.append("composer install")
        elif pm == "dotnet":
            commands.append("dotnet restore")
    return commands


def _tool_steps(tool_name, capability, record, platform, repo_ctx) -> list[IRStep]:
    """Steps for one tool: install (if needed) + run. Binary-only tools get a
    combined install+run step so PATH handling stays portable."""
    if tool_name in ("go-test", "cargo-test", "npm-audit", "docker") or (
        record is not None and record.versions == ["bundled"]
    ):
        installs: list[str] = []
    else:
        installs = _install_commands(tool_name, record, platform)
    try:
        command = command_for(tool_name)
    except KeyError:
        return [IRStep(id="", name=f"{tool_name} (unsupported)", capability=capability,
                       tool=tool_name, run=f'echo "no canonical command for {tool_name}" && exit 1')]
    condition = condition_for(tool_name)

    action_uses, action_args = _github_action_for(tool_name, record, platform)
    if action_uses:
        steps = [IRStep(id="", name=f"Run {tool_name}", capability=capability,
                        tool=tool_name, uses=action_uses, with_args=action_args, condition=condition)]
        if tool_name == "cosign":
            steps.append(IRStep(id="", name="Sign SBOM (keyless)", capability=capability,
                                tool=tool_name, run=command))
        return steps
    if installs and _is_portable_installer(installs[0]):
        combined = f"{installs[0]} && {command}" if _is_binary_url_install(tool_name, record) else None
        if combined:
            return [IRStep(id="", name=f"Install and run {tool_name}", capability=capability,
                           tool=tool_name, run=combined, condition=condition)]
        steps = [IRStep(id="", name=f"Install {tool_name}", capability=capability,
                        tool=tool_name, run=" && ".join(installs))]
        steps.append(IRStep(id="", name=f"Run {tool_name}", capability=capability,
                            tool=tool_name, run=command, condition=condition))
        return steps
    if installs:
        steps = [IRStep(id="", name=f"Install {tool_name}", capability=capability,
                        tool=tool_name, run=" && ".join(installs))]
        steps.append(IRStep(id="", name=f"Run {tool_name}", capability=capability,
                            tool=tool_name, run=command, condition=condition))
        return steps
    return [IRStep(id="", name=f"Run {tool_name}", capability=capability,
                   tool=tool_name, run=command, condition=condition)]


def _install_commands(tool_name, record, platform) -> list[str]:
    if record is not None:
        pkg = [i.command for i in record.install_methods if i.type in PKG_INSTALL_TYPES]
        if pkg:
            if record.versions and record.versions[0] not in ("unknown", "bundled"):
                return [pkg[0]]  # knowledge commands already carry pins
            return [pkg[0]]
        urls = [i.command for i in record.install_methods if i.type == "binary"]
        if urls:
            return [_binary_installer(tool_name, urls[0])]
        scripts = [i.command for i in record.install_methods if "install.sh" in i.command]
        if scripts:
            return scripts[:1]
    fallback = FALLBACK_INSTALL.get(tool_name)
    return [fallback] if fallback else []


def _binary_installer(tool_name: str, url: str) -> str:
    url = url.strip()
    if url.startswith(("http://", "https://")):
        dl = f"/tmp/{tool_name}.dl"
        return (
            f"mkdir -p $HOME/.local/bin && curl -sSfL -o {dl} {url} && "
            f"(tar -xzf {dl} -C $HOME/.local/bin {tool_name} 2>/dev/null || "
            f"cp {dl} $HOME/.local/bin/{tool_name}) && chmod +x $HOME/.local/bin/{tool_name} && "
            f"export PATH=$HOME/.local/bin:$PATH"
        )
    return url


def _is_binary_url_install(tool_name, record) -> bool:
    if record is None:
        return False
    has_pkg = any(i.type in PKG_INSTALL_TYPES for i in record.install_methods)
    has_url = any(i.type == "binary" and i.command.strip().startswith(("http://", "https://"))
                  for i in record.install_methods)
    return has_url and not has_pkg


def _is_portable_installer(command: str) -> bool:
    return True


def _github_action_for(tool_name, record, platform) -> tuple[str, dict]:
    """Official action install (github only), e.g. trivy-action runs the scan
    itself. With-args come from the renderer's default table."""
    if platform != "github" or record is None:
        return "", {}
    from .actions import ACTION_DEFAULT_ARGS, KNOWN_ACTION_VERSIONS

    for method in record.install_methods:
        if method.type != "action":
            continue
        uses = method.command.strip()
        name = uses.split("@")[0]
        if name in KNOWN_ACTION_VERSIONS:
            pinned = f"{name}@{KNOWN_ACTION_VERSIONS[name]}"
            return pinned, dict(ACTION_DEFAULT_ARGS.get(name, {}))
    return "", {}


def _runtime_version(ecosystem: str, repo_ctx: RepositoryContext, default: str) -> str:
    for lang in repo_ctx.languages:
        if lang.name != ecosystem or not lang.version_constraint:
            continue
        m = re.search(r"(\d+(?:\.\d+){0,2})", lang.version_constraint)
        if m:
            return m.group(1)
    return default
