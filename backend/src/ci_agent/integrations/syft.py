"""SBOM generation via Syft (Phase 4). No custom SBOM engine — if Syft is
absent the step is explicitly skipped, never faked."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..common.models import SBOMResult
from ..common.util import sha256_text
from ..config import Settings
from ..observability.logging import get_logger
from ..observability.metrics import TOOL_CALLS

LOG = get_logger("ci_agent.integrations.syft")


def generate_sbom(source_path: Path, out_path: Path, settings: Settings) -> SBOMResult:
    _ = settings
    binary = shutil.which("syft")
    if not binary:
        LOG.warning("syft not installed — sbom step skipped")
        return SBOMResult(provenance={"runner": "skipped", "reason": "syft-binary-not-installed"})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            [binary, str(source_path), "-o", f"cyclonedx-json={out_path}"],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        TOOL_CALLS.labels(tool="syft", status="timeout").inc()
        return SBOMResult(provenance={"runner": "binary", "reason": "timeout"})
    if proc.returncode != 0:
        TOOL_CALLS.labels(tool="syft", status="error").inc()
        return SBOMResult(provenance={"runner": "binary", "reason": proc.stderr[-300:]})
    TOOL_CALLS.labels(tool="syft", status="ok").inc()
    package_count = 0
    digest = ""
    try:
        text = out_path.read_text(encoding="utf-8")
        digest = "sha256:" + sha256_text(text)
        package_count = len(json.loads(text).get("components", []) or [])
    except (OSError, json.JSONDecodeError):
        pass
    LOG.info("sbom generated packages=%d digest=%s", package_count, digest[:20])
    return SBOMResult(format="cyclonedx-json", package_count=package_count,
                      sbom_path=str(out_path), digest=digest, provenance={"runner": "binary"})
