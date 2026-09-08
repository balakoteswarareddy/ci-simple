"""Artifact signing via Cosign/Sigstore (Phase 4). Keyless by default
(OIDC); COSIGN_KEY_REF selects a key when provided. No custom signing code.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..common.models import SignResult
from ..common.util import sha256_text
from ..config import Settings
from ..observability.logging import get_logger
from ..observability.metrics import TOOL_CALLS

LOG = get_logger("ci_agent.integrations.cosign")


def sign_blob(artifact: Path, settings: Settings) -> SignResult:
    binary = shutil.which("cosign")
    if not binary:
        LOG.warning("cosign not installed — sign step skipped")
        return SignResult(artifact=str(artifact),
                          provenance={"runner": "skipped", "reason": "cosign-binary-not-installed"})
    try:
        digest = "sha256:" + sha256_text(artifact.read_bytes().decode("utf-8", errors="replace"))
    except OSError as exc:
        return SignResult(artifact=str(artifact), provenance={"runner": "binary", "reason": f"read failed: {exc}"})
    sig_path = artifact.with_suffix(artifact.suffix + ".sig")
    cert_path = artifact.with_suffix(artifact.suffix + ".pem")
    argv = [binary, "sign-blob", "--yes", str(artifact),
           "--output-signature", str(sig_path), "--output-certificate", str(cert_path)]
    if settings.cosign_key_ref:
        argv += ["--key", settings.cosign_key_ref]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        TOOL_CALLS.labels(tool="cosign", status="timeout").inc()
        return SignResult(artifact=str(artifact), digest=digest,
                          provenance={"runner": "binary", "reason": "timeout"})
    if proc.returncode != 0:
        TOOL_CALLS.labels(tool="cosign", status="error").inc()
        hint = proc.stderr[-300:]
        if "OIDC" in proc.stderr or "token" in proc.stderr.lower():
            hint += " (keyless signing needs an OIDC identity — runs inside CI)"
        return SignResult(artifact=str(artifact), digest=digest,
                          provenance={"runner": "binary", "reason": hint})
    TOOL_CALLS.labels(tool="cosign", status="ok").inc()
    LOG.info("signed artifact=%s", artifact.name)
    return SignResult(artifact=str(artifact), signature_path=str(sig_path),
                      certificate=str(cert_path), digest=digest, provenance={"runner": "binary"})
