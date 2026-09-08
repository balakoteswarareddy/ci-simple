"""Chainloop evidence adapter (Phase 4: supply-chain evidence/provenance).

Thin client: pushes the signed attestation envelope to a Chainloop control
plane when configured. Unconfigured -> explicit 'disabled' status and the
evidence stays in the local immutable store (evidence/ + DB).
"""
from __future__ import annotations

import httpx

from ..config import Settings
from ..observability.logging import get_logger
from ..observability.metrics import TOOL_CALLS

LOG = get_logger("ci_agent.integrations.chainloop")


class ChainloopClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.plane = settings.chainloop_control_plane.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.plane)

    async def push_attestation(self, envelope: dict) -> dict:
        if not self.enabled:
            return {"status": "disabled",
                    "reason": "CHAINLOOP_CONTROL_PLANE unset — evidence stored locally only"}
        headers = {"Content-Type": "application/json", "User-Agent": "ci-agent/0.1"}
        if self.settings.chainloop_robot_account:
            headers["Authorization"] = f"Bearer {self.settings.chainloop_robot_account}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.plane}/api/v1/attestations", headers=headers, json=envelope)
        except Exception as exc:
            TOOL_CALLS.labels(tool="chainloop", status="error").inc()
            return {"status": "error", "reason": f"control plane unreachable: {exc}"}
        if response.status_code >= 400:
            TOOL_CALLS.labels(tool="chainloop", status="error").inc()
            return {"status": "error",
                    "reason": f"HTTP {response.status_code}: {response.text[:300]}"}
        TOOL_CALLS.labels(tool="chainloop", status="ok").inc()
        LOG.info("pushed attestation to chainloop")
        return {"status": "pushed", "response": response.json() if response.content else {}}

    def push_attestation_sync(self, envelope: dict) -> dict:
        """Synchronous variant for the evidence finalizer (sync context)."""
        if not self.enabled:
            return {"status": "disabled",
                    "reason": "CHAINLOOP_CONTROL_PLANE unset — evidence stored locally only"}
        headers = {"Content-Type": "application/json", "User-Agent": "ci-agent/0.1"}
        if self.settings.chainloop_robot_account:
            headers["Authorization"] = "Bearer {masked}"
        try:
            with httpx.Client(timeout=30) as client:
                headers_real = dict(headers)
                if self.settings.chainloop_robot_account:
                    headers_real["Authorization"] = f"Bearer {self.settings.chainloop_robot_account}"
                response = client.post(
                    f"{self.plane}/api/v1/attestations", headers=headers_real, json=envelope)
        except Exception as exc:
            TOOL_CALLS.labels(tool="chainloop", status="error").inc()
            return {"status": "error", "reason": f"control plane unreachable: {exc}"}
        if response.status_code >= 400:
            TOOL_CALLS.labels(tool="chainloop", status="error").inc()
            return {"status": "error",
                    "reason": f"HTTP {response.status_code}: {response.text[:300]}"}
        TOOL_CALLS.labels(tool="chainloop", status="ok").inc()
        return {"status": "pushed", "response": response.json() if response.content else {}}

    def build_envelope(self, evidence: dict, digests: dict[str, str]) -> dict:
        """Wrap the local DecisionEvidence into a generic attestation envelope."""
        return {
            "schema": "ci-agent.attestation/v1",
            "run_id": evidence.get("run_id", ""),
            "repo": {"url": evidence.get("repo_url", ""), "revision": evidence.get("commit_sha", "")},
            "artifacts": [{"name": name, "digest": digest} for name, digest in digests.items()],
            "policy": (evidence.get("policy") or {}).get("decision", ""),
            "approval": evidence.get("approval"),
            "evidence_hash": evidence.get("evidence_hash", ""),
        }
