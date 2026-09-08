"""actionlint integration (PDF §5 step 9): purpose-built static checker for
GitHub Actions workflows. Missing binary -> explicit skip (warning), never a
silent pass and never a hard failure.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from ..common.models import ValidationFinding, ValidationResult
from ..config import Settings
from ..observability.logging import get_logger

LOG = get_logger("ci_agent.validation")

OUTPUT_RE = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+): (?P<msg>.+?)(?: \[(?P<check>[^\]]+)\])?$")


def find_binary(settings: Settings) -> str:
    import os

    explicit = os.environ.get("ACTIONLINT_BIN", "")
    if explicit:
        return explicit
    found = shutil.which("actionlint")
    return found or ""


def binary_version(binary: str) -> str:
    try:
        proc = subprocess.run([binary, "-version"], capture_output=True, text=True, timeout=15)
        out = (proc.stdout + proc.stderr).strip().splitlines()
        return out[0][:64] if out else ""
    except Exception:
        return ""


def run_actionlint(workflow_path: Path, settings: Settings) -> ValidationResult:
    started = time.monotonic()
    binary = find_binary(settings)
    if not binary or not Path(binary).exists() and not shutil.which(binary):
        return ValidationResult(
            validator="actionlint",
            passed=True,
            warnings=[ValidationFinding(
                validator="actionlint", level="warning",
                message="actionlint binary not installed — static check skipped",
                file=str(workflow_path),
                remediation="install actionlint (see LOCAL_SERVICES.md) or run via the api container",
            )],
            duration_ms=_elapsed(started),
            provenance={"runner": "skipped", "reason": "binary-not-installed"},
        )
    version = binary_version(binary)
    try:
        proc = subprocess.run(
            [binary, "-no-color", "-format", "{{.Filepath}}:{{.Line}}:{{.Column}}: {{.Message}} [{{.Kind}}]",
             str(workflow_path)],
            capture_output=True, text=True, timeout=120,
        )
    except Exception as exc:
        return ValidationResult(
            validator="actionlint", version=version, passed=False,
            errors=[ValidationFinding(validator="actionlint", message=f"actionlint execution failed: {exc}")],
            duration_ms=_elapsed(started),
            provenance={"runner": "binary", "reason": "execution-failed"},
        )
    errors: list[ValidationFinding] = []
    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        line = line.strip()
        if not line:
            continue
        match = OUTPUT_RE.match(line)
        if match:
            errors.append(ValidationFinding(
                validator="actionlint", version=version, level="error",
                message=match.group("msg"), file=match.group("file"),
                line=int(match.group("line")),
                remediation=f"actionlint rule: {match.group('check') or 'syntax'}",
            ))
        else:
            errors.append(ValidationFinding(
                validator="actionlint", version=version, message=line, file=str(workflow_path)))
    passed = proc.returncode == 0 and not errors
    LOG.info("actionlint file=%s passed=%s findings=%d", workflow_path.name, passed, len(errors))
    return ValidationResult(
        validator="actionlint", version=version, passed=passed, errors=errors,
        duration_ms=_elapsed(started), provenance={"runner": "binary"},
    )


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
