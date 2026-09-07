"""Deterministic schema checks: IR invariants + rendered artifact parsing."""
from __future__ import annotations

import time

import yaml

from ..common.models import PipelineIR, ValidationFinding, ValidationResult
from ..observability.logging import get_logger

LOG = get_logger("ci_agent.validation")


def check_ir(ir: PipelineIR) -> ValidationResult:
    started = time.monotonic()
    errors: list[ValidationFinding] = []
    warnings: list[ValidationFinding] = []

    def err(message: str, remediation: str = "") -> None:
        errors.append(ValidationFinding(validator="ir-schema", message=message, remediation=remediation))

    if ir.version != "1.0":
        err(f"unsupported IR version '{ir.version}'", "regenerate with the current agent")
    if ir.platform not in ("github", "azure", "gitlab", "jenkins"):
        err(f"unknown platform '{ir.platform}'")
    if not ir.jobs:
        err("IR has no jobs", "request at least one capability with a grounded tool")

    job_ids = [job.id for job in ir.jobs]
    if len(set(job_ids)) != len(job_ids):
        err("duplicate job ids in IR")
    for job in ir.jobs:
        for need in job.needs:
            if need not in job_ids:
                err(f"job '{job.id}' needs unknown job '{need}'")
        if not job.steps:
            err(f"job '{job.id}' has no steps")
        step_ids = [s.id for s in job.steps]
        if len(set(step_ids)) != len(step_ids):
            err(f"job '{job.id}' has duplicate step ids")
        for step in job.steps:
            if bool(step.uses) == bool(step.run):
                err(f"step '{step.id}' must set exactly one of uses/run")
            if step.uses and "@" not in step.uses:
                err(f"step '{step.id}' uses unpinned action '{step.uses}'",
                    "pin to name@version (see pipeline/actions.py)")
    if _has_cycle(ir):
        err("job dependency cycle detected")

    if not ir.triggers:
        warnings.append(ValidationFinding(validator="ir-schema", level="warning", message="IR has no triggers"))
    LOG.info("ir-schema passed=%s errors=%d", not errors, len(errors))
    return ValidationResult(
        validator="ir-schema", version="1.0", passed=not errors,
        errors=errors, warnings=warnings,
        duration_ms=int((time.monotonic() - started) * 1000),
        provenance={"runner": "builtin"},
    )


def _has_cycle(ir: PipelineIR) -> bool:
    graph = {job.id: set(job.needs) for job in ir.jobs}
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str) -> bool:
        if node in done:
            return False
        if node in visiting:
            return True
        visiting.add(node)
        for dep in graph.get(node, ()):  # noqa: B007 - dep used below
            if dep in graph and visit(dep):
                return True
        visiting.remove(node)
        done.add(node)
        return False

    return any(visit(job_id) for job_id in graph)


def check_rendered(content: str, platform: str, filename: str) -> ValidationResult:
    started = time.monotonic()
    errors: list[ValidationFinding] = []

    def err(message: str, remediation: str = "") -> None:
        errors.append(ValidationFinding(
            validator="render-schema", message=message, file=filename, remediation=remediation))

    if platform == "jenkins":
        stripped = content.strip()
        if "pipeline {" not in stripped:
            err("Jenkinsfile is missing the 'pipeline' block")
        if stripped.count("{") != stripped.count("}"):
            err("Jenkinsfile has unbalanced braces")
    else:
        try:
            doc = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            err(f"rendered YAML does not parse: {exc}")
            doc = None
        if isinstance(doc, dict):
            if platform == "github":
                if "jobs" not in doc:
                    err("github workflow is missing 'jobs'")
                if not any(k in doc for k in ("on", True)):
                    err("github workflow is missing 'on' triggers")
                if "permissions" not in doc:
                    err("github workflow is missing top-level 'permissions'",
                        "least privilege is mandatory (§10)")
            elif platform == "azure":
                if "jobs" not in doc:
                    err("azure pipeline is missing 'jobs'")
            elif platform == "gitlab":
                if "stages" not in doc:
                    err("gitlab pipeline is missing 'stages'")
        elif doc is not None:
            err("rendered document is not a mapping")

    LOG.info("render-schema platform=%s passed=%s", platform, not errors)
    return ValidationResult(
        validator="render-schema", passed=not errors, errors=errors,
        duration_ms=int((time.monotonic() - started) * 1000),
        provenance={"runner": "builtin"},
    )
