"""Validation orchestrator: runs every validator and aggregates results."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from ..common.models import PipelineIR, ValidationResult
from ..common.util import utcnow
from ..config import Settings
from ..observability.logging import get_logger
from ..observability.metrics import VALIDATION_FINDINGS
from ..pipeline.render import RenderedOutput
from ..policy.catalog import get_catalog
from .actionlint import run_actionlint
from .schema_checks import check_ir, check_rendered
from .security_checks import check_workflow

LOG = get_logger("ci_agent.validation")


async def run_all(
    ir: PipelineIR,
    rendered: RenderedOutput,
    settings: Settings,
    work_dir: Path,
) -> list[ValidationResult]:
    started = time.monotonic()
    workflow_path = work_dir / rendered.filename
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(rendered.content, encoding="utf-8")

    catalog = get_catalog(settings)
    results: list[ValidationResult] = [
        check_ir(ir),
        check_rendered(rendered.content, ir.platform, rendered.filename),
        check_workflow(ir, rendered.content, catalog),
    ]
    if ir.platform == "github":
        results.append(await asyncio.to_thread(run_actionlint, workflow_path, settings))

    for result in results:
        for finding in result.errors:
            VALIDATION_FINDINGS.labels(validator=result.validator, level="error").inc()
        for finding in result.warnings:
            VALIDATION_FINDINGS.labels(validator=result.validator, level="warning").inc()
    LOG.info("validation complete passed=%s validators=%d elapsed_ms=%d",
             all_passed(results), len(results), int((time.monotonic() - started) * 1000))
    return results


def all_passed(results: list[ValidationResult]) -> bool:
    return all(r.passed for r in results)


def skipped_validators(results: list[ValidationResult]) -> list[str]:
    return [r.validator for r in results if r.provenance.get("runner") == "skipped"]


def failures_text(results: list[ValidationResult]) -> str:
    """Compact failure listing fed back to the planner/refiner (§5 step 10)."""
    lines: list[str] = []
    for result in results:
        for finding in result.errors:
            where = f"{finding.file}:{finding.line}" if finding.file else result.validator
            lines.append(f"[{result.validator}] {where} {finding.message}")
    return "\n".join(lines) if lines else "(no failures)"


def ir_summary(ir: PipelineIR) -> str:
    """Compact IR listing so repairs can target job/step ids."""
    lines: list[str] = []
    for job in ir.jobs:
        for step in job.steps:
            lines.append(f"job={job.id} step={step.id} uses={step.uses} run={step.run[:80]} tool={step.tool}")
    lines.append(f"permissions={ir.permissions}")
    return "\n".join(lines)
