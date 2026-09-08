"""Higher-level security checks over the IR + rendered workflow (PDF §5
step 9 "our own higher-level checks"). Defense in depth behind OPA: the
renderer should already guarantee these, we verify anyway."""
from __future__ import annotations

import re
import time

from ..common.models import PipelineIR, ValidationFinding, ValidationResult
from ..observability.logging import get_logger
from ..pipeline.actions import is_approved_action
from ..policy.catalog import PolicyCatalog

LOG = get_logger("ci_agent.validation")

SECRET_RE = re.compile(
    r"(?i)gh[opsu]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|"
    r"(password|passwd|secret|api[_-]?key)\s*[:=]\s*['\"]?[^\s'\"]{4,}"
)
INJECTION_RE = re.compile(r"\$\{\{\s*github\.event\.(issue|comment|pull_request|head_commit|commits)")
CURL_PIPE_RE = re.compile(r"curl\b[^\n|]*\|\s*(ba)?sh")
PR_TARGET_RE = re.compile(r"pull_request_target")


def check_workflow(ir: PipelineIR, content: str, catalog: PolicyCatalog) -> ValidationResult:
    started = time.monotonic()
    errors: list[ValidationFinding] = []
    warnings: list[ValidationFinding] = []

    def err(message: str, remediation: str = "") -> None:
        errors.append(ValidationFinding(validator="workflow-security", message=message, remediation=remediation))

    def warn(message: str, remediation: str = "") -> None:
        warnings.append(ValidationFinding(
            validator="workflow-security", level="warning", message=message, remediation=remediation))

    # -- IR-level: every uses: must be approved + pinned ------------------
    for job in ir.jobs:
        for step in job.steps:
            if not step.uses:
                continue
            if not is_approved_action(step.uses, catalog.action_prefixes):
                err(f"step '{step.id}' uses non-approved action '{step.uses}'",
                    "use an action from the approved catalog")
            ref = step.uses.split("@", 1)[1] if "@" in step.uses else ""
            if not ref or ref in ("main", "master", "latest"):
                err(f"step '{step.id}' uses floating ref '{step.uses}'",
                    "pin to an immutable version")

    # -- permission hygiene -------------------------------------------------
    for scope, value in ir.permissions.items():
        if scope not in catalog.known_permissions:
            err(f"unknown permission scope '{scope}'")
        if value == "write":
            warn(f"workflow requests '{scope}: write' — ensure approval was recorded",
                 "least privilege (§10); writes need human review")

    # -- rendered content ----------------------------------------------------
    if SECRET_RE.search(content):
        err("rendered workflow appears to contain a secret value",
            "use secret stores / OIDC, never inline credentials")
    if PR_TARGET_RE.search(content):
        err("pull_request_target trigger is dangerous with checkouts",
            "avoid pull_request_target or isolate it without secrets")
    for match in INJECTION_RE.finditer(content):
        warn(f"possible script injection via untrusted context '{match.group(0)}'",
             "assign the expression to an env var instead of inline expansion")
    for match in CURL_PIPE_RE.finditer(content):
        warn(f"curl-piped-to-shell installer: {match.group(0)[:80]}",
            "prefer pinned package installs or verified release artifacts")

    LOG.info("workflow-security passed=%s errors=%d warnings=%d", not errors, len(errors), len(warnings))
    return ValidationResult(
        validator="workflow-security", version="1.0", passed=not errors,
        errors=errors, warnings=warnings,
        duration_ms=int((time.monotonic() - started) * 1000),
        provenance={"runner": "builtin"},
    )
