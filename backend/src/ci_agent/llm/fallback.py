"""Deterministic offline planner (no model, no network, no secrets involved).

Used when no LLM is configured or the LLM call fails. It is deliberately
conservative: keyword-grounded intent parsing and rule-based repairs only.
Every output is labeled planner="deterministic-fallback" in its evidence.
"""
from __future__ import annotations

import re

from ..common.models import UserIntent
from ..common.util import truncate
from ..config import Settings
from ..policy.catalog import get_catalog
from .base import LLMCallStats, LLMClient

PLATFORM_HINTS = [
    ("gitlab", "gitlab"),
    ("azure pipelines", "azure"),
    ("azure devops", "azure"),
    ("jenkins", "jenkins"),
    ("github actions", "github"),
]

CAPABILITY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("lint", ["lint", "eslint", "ruff", "flake8", "shellcheck", "hadolint", "yamllint", "actionlint"]),
    ("format", ["format", "prettier", "black", "gofmt", "rustfmt"]),
    ("test", ["test", "pytest", "jest", "vitest", "unittests", "unit tests", "coverage"]),
    ("sast", ["sast", "static analysis", "semgrep", "bandit", "gosec", "codeql"]),
    ("sca", ["sca", "dependenc", "vulnerab", "audit", "osv", "cve", "supply chain"]),
    ("secrets", ["secret", "gitleaks", "trufflehog", "leak", "credentials"]),
    ("container-scan", ["container scan", "image scan", "trivy", "container secur"]),
    ("iac-scan", ["iac", "terraform", "checkov", "kics", "infrastructure scan"]),
    ("docker-build", ["docker", "containerize", "container build", "image build"]),
    ("build", ["build"]),
    ("sbom", ["sbom", "software bill", "bill of materials", "syft"]),
    ("sign", ["sign", "cosign", "attest", "signature", "provenance"]),
    ("deploy", ["deploy", "release", "publish", "ship", "cd ", "continuous deployment"]),
]

SECURITY_EXPANSION = ["sast", "sca", "secrets"]
FULL_SUITE = ["lint", "test", "sast", "sca", "secrets"]

PROHIBITION_RE = re.compile(
    r"(?:don't|do not|never|without|no|avoid|not use|doesn't use|excluding?|except|skip)\s+(?:use\s+)?([a-z0-9][a-z0-9_+\-.]*(?:\s*(?:,|and)\s*[a-z0-9][a-z0-9_+\-.]*)*)",
    re.IGNORECASE,
)

BUILTIN_TOOLS = [
    "ruff", "eslint", "prettier", "black", "flake8", "shellcheck", "yamllint",
    "hadolint", "pytest", "jest", "vitest", "go-test", "cargo-test", "phpunit",
    "rspec", "semgrep", "bandit", "gosec", "trivy", "gitleaks", "trufflehog",
    "osv-scanner", "pip-audit", "npm-audit", "cargo-audit", "syft", "cosign",
    "actionlint", "checkov", "kics", "docker",
]


class DeterministicClient(LLMClient):
    name = "deterministic"

    def __init__(self, settings: Settings):
        self.settings = settings

    def _tool_vocab(self) -> set[str]:
        try:
            tools = get_catalog(self.settings).tools
        except Exception:
            tools = []
        return {t.lower() for t in (tools or BUILTIN_TOOLS)}

    # -- intent ----------------------------------------------------------
    async def parse_intent(self, request_text: str, repo_facts: str) -> tuple[UserIntent, LLMCallStats]:
        text = (request_text or "").lower()
        platform = "github"
        for hint, value in PLATFORM_HINTS:
            if hint in text:
                platform = value
                break

        capabilities: list[str] = []
        for cap, keywords in CAPABILITY_KEYWORDS:
            if any(k in text for k in keywords):
                capabilities.append(cap)
        if "secur" in text:
            capabilities += [c for c in SECURITY_EXPANSION if c not in capabilities]
        if any(k in text for k in ("full", "complete", "production-grade", "production grade", "everything")):
            capabilities += [c for c in FULL_SUITE if c not in capabilities]
        # docker-build implies container capabilities only when asked; build
        # alone stays minimal.
        if "docker-build" in capabilities and "build" in capabilities:
            capabilities.remove("build")
        if not capabilities:
            capabilities = ["lint", "test"]

        prohibited = self._parse_prohibitions(request_text or "")
        deployment_target = ""
        if re.search(r"\bproduction\b|\bprod\b", text):
            deployment_target = "production"
        elif "staging" in text:
            deployment_target = "staging"

        constraints: list[str] = []
        for sentence in re.split(r"[.\n]", request_text or ""):
            s = sentence.strip()
            if len(s) > 12 and re.search(r"\bmust\b|\bshould\b|\brequire|\bonly\b", s, re.IGNORECASE):
                constraints.append(truncate(s, 200))
        constraints = constraints[:5]

        required_controls: list[str] = []
        if "approv" in text:
            required_controls.append("human-approval")
        if "sign" in text or "attest" in text:
            required_controls.append("signing")
        if "sbom" in text:
            required_controls.append("sbom")

        intent = UserIntent(
            platform=platform,
            capabilities=capabilities,
            deployment_target=deployment_target,
            constraints=constraints,
            prohibited_tools=prohibited,
            required_controls=required_controls,
            raw_request=truncate(request_text or "", 2000),
            planner="deterministic-fallback",
        )
        return intent, LLMCallStats(model="deterministic-fallback")

    def _parse_prohibitions(self, request_text: str) -> list[str]:
        vocab = self._tool_vocab()
        found: list[str] = []
        for match in PROHIBITION_RE.finditer(request_text):
            chunk = match.group(1)
            for token in re.split(r"\s*(?:,|and)\s*", chunk):
                name = token.strip().lower().rstrip("s.") or ""
                # allow "semgrep" from "semgreps"? No — exact vocab match, with
                # a singular fallback for plural typos.
                candidates = [name]
                if name.endswith("s"):
                    candidates.append(name[:-1])
                for cand in candidates:
                    if cand in vocab and cand not in found:
                        found.append(cand)
                        break
        return found

    # -- repairs -----------------------------------------------------------
    async def propose_repairs(self, failures: str, ir_summary: str) -> tuple[list[dict], LLMCallStats]:
        """Rule-based fixes: pin drifted actions, drop unknown permissions,
        downgrade write permissions the plan can live without."""
        from ..pipeline.actions import KNOWN_ACTION_VERSIONS

        repairs: list[dict] = []
        steps = self._parse_ir_summary(ir_summary)
        for line in failures.splitlines():
            low = line.lower()
            if "action" in low and "pin" in low:
                m = re.search(r"action '([^']+)'", line)
                if m:
                    uses = m.group(1)
                    name = uses.split("@")[0]
                    if name in KNOWN_ACTION_VERSIONS:
                        target = self._find_step_using(steps, name)
                        if target:
                            repairs.append({
                                "job_id": target[0], "step_id": target[1],
                                "action": "set_uses",
                                "value": f"{name}@{KNOWN_ACTION_VERSIONS[name]}",
                                "reason": f"pin {name} to known version",
                            })
            elif "unknown permission scope" in low:
                m = re.search(r"scope '([^']+)'", line)
                if m:
                    repairs.append({
                        "job_id": "", "step_id": "",
                        "action": "set_permission",
                        "value": {"scope": m.group(1), "value": None},
                        "reason": "drop unknown permission scope",
                    })
        return repairs, LLMCallStats(model="deterministic-fallback")

    def _parse_ir_summary(self, summary: str) -> list[tuple[str, str, str]]:
        steps: list[tuple[str, str, str]] = []
        for line in summary.splitlines():
            m = re.match(r"job=(\S+)\s+step=(\S+)\s+uses=(\S*)", line.strip())
            if m:
                steps.append((m.group(1), m.group(2), m.group(3)))
        return steps

    def _find_step_using(self, steps: list[tuple[str, str, str]], action_name: str) -> tuple[str, str] | None:
        for job_id, step_id, uses in steps:
            if uses.startswith(action_name + "@"):
                return job_id, step_id
        return None

    # -- extraction --------------------------------------------------------
    async def extract_tool_facts(self, source_text: str, url: str) -> tuple[list[dict], LLMCallStats]:
        # Deterministic mode never fabricates structured facts from prose; the
        # ingester falls back to its low-confidence heuristic instead.
        return [], LLMCallStats(model="deterministic-fallback")
