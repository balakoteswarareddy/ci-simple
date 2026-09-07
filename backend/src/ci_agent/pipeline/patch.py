"""Bounded IR patching (Phase 6 repair loop).

Repair proposals (LLM or rule-based) may only touch the IR through these
typed actions — never free-form YAML. Safety guards:
- `uses:` values must come from the approved action catalog.
- `run:` values must equal the canonical command for the step's tool, or be
  an `echo` placeholder for tool-less steps. The model cannot inject shell.
"""
from __future__ import annotations

from ..common.models import IRJob, IRStep, PipelineIR
from ..observability.logging import get_logger
from ..policy.catalog import PolicyCatalog
from .actions import KNOWN_ACTION_VERSIONS, is_approved_action
from .commands import TOOL_COMMANDS

LOG = get_logger("ci_agent.pipeline.patch")

RUNS_ON_ALLOWLIST = {"ubuntu-latest", "ubuntu-22.04", "windows-latest", "macos-latest"}
PERMISSION_VALUES = {"read", "write", "none", None}


def apply_repairs(
    ir: PipelineIR, repairs: list[dict], catalog: PolicyCatalog
) -> tuple[PipelineIR, list[str]]:
    notes: list[str] = []
    jobs: dict[str, IRJob] = {job.id: job.model_copy(deep=True) for job in ir.jobs}
    permissions = dict(ir.permissions)

    for index, repair in enumerate(repairs):
        label = f"repair[{index}]"
        action = str(repair.get("action", ""))
        job_id = str(repair.get("job_id", ""))
        step_id = str(repair.get("step_id", ""))
        value = repair.get("value")
        try:
            if action == "set_permission":
                _apply_permission(permissions, value, catalog)
                notes.append(f"{label}: permission updated to {value}")
            elif action not in {"set_uses", "set_run", "add_step", "remove_step", "set_with", "set_runs_on", "rename"}:
                notes.append(f"{label}: unknown action '{action}' — rejected")
            elif job_id not in jobs:
                notes.append(f"{label}: unknown job '{job_id}' — rejected")
            else:
                _apply_job_action(jobs[job_id], action, step_id, value, catalog)
                notes.append(f"{label}: applied {action} on {job_id}/{step_id or '-'}")
        except ValueError as exc:
            notes.append(f"{label}: rejected ({exc})")

    new_ir = ir.model_copy(deep=True)
    new_ir.jobs = [jobs[j.id] for j in ir.jobs]
    new_ir.permissions = permissions
    # Keep job-level permissions in sync with top-level least privilege.
    for job in new_ir.jobs:
        job.permissions = dict(permissions)
    applied = sum(1 for n in notes if "applied" in n or "updated" in n)
    LOG.info("applied %d/%d repairs", applied, len(repairs))
    return new_ir, notes


def _apply_permission(permissions: dict, value, catalog: PolicyCatalog) -> None:
    if not isinstance(value, dict):
        raise ValueError("set_permission needs {'scope': ..., 'value': ...}")
    scope = str(value.get("scope", ""))
    val = value.get("value")
    if scope not in catalog.known_permissions:
        raise ValueError(f"unknown permission scope '{scope}'")
    if val not in PERMISSION_VALUES:
        raise ValueError(f"bad permission value '{val}'")
    if val is None:
        permissions.pop(scope, None)
    else:
        permissions[scope] = val


def _apply_job_action(job: IRJob, action: str, step_id: str, value, catalog: PolicyCatalog) -> None:
    if action == "set_runs_on":
        if str(value) not in RUNS_ON_ALLOWLIST:
            raise ValueError(f"runs-on '{value}' not allow-listed")
        job.runs_on = str(value)
        return
    if action == "rename":
        job.name = str(value)[:120]
        return
    if action == "add_step":
        if not isinstance(value, dict):
            raise ValueError("add_step needs a step object")
        step = IRStep(**value)
        _check_step(step, catalog)
        job.steps.append(step)
        return
    step = next((s for s in job.steps if s.id == step_id), None)
    if step is None:
        raise ValueError(f"unknown step '{step_id}' in job '{job.id}'")
    if action == "remove_step":
        job.steps = [s for s in job.steps if s.id != step_id]
    elif action == "set_uses":
        uses = str(value)
        if not is_approved_action(uses, catalog.action_prefixes):
            raise ValueError(f"action '{uses}' is not approved")
        step.uses = uses
        step.run = ""
    elif action == "set_run":
        _check_run(step, str(value))
        step.run = str(value)
        step.uses = ""
    elif action == "set_with":
        if not isinstance(value, dict):
            raise ValueError("set_with needs an object")
        step.with_args.update({str(k): v for k, v in value.items()})
    else:
        raise ValueError(f"unsupported action '{action}'")


def _check_step(step: IRStep, catalog: PolicyCatalog) -> None:
    if step.uses and not is_approved_action(step.uses, catalog.action_prefixes):
        raise ValueError(f"action '{step.uses}' is not approved")
    if step.run:
        _check_run(step, step.run)


def _check_run(step: IRStep, run: str) -> None:
    """The model may only restore canonical commands or echo placeholders."""
    if step.tool and step.tool in TOOL_COMMANDS:
        if run.strip() != TOOL_COMMANDS[step.tool]:
            raise ValueError(f"run for tool '{step.tool}' must be its canonical command")
        return
    if step.tool and step.tool != "setup":
        raise ValueError(f"no canonical command known for tool '{step.tool}'")
    if not run.strip().startswith("echo "):
        raise ValueError("tool-less steps may only run echo placeholders")
