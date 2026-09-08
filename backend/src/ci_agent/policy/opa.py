"""OPA server client (PDF §5 step 6: OPA is the policy decision point).

The Rego bundle lives in deploy/opa/store (mounted into the OPA container).
Any communication failure raises OPAError — callers fail closed.
"""
from __future__ import annotations

from ..common.models import PolicyDecision, PolicyFinding
from ..common.util import utcnow
from ..config import Settings
from ..observability.logging import get_logger

LOG = get_logger("ci_agent.policy")


class OPAError(RuntimeError):
    pass


class OPAClient:
    def __init__(self, settings: Settings):
        if not settings.opa_url:
            raise OPAError("OPA_URL is not configured")
        self.base_url = settings.opa_url.rstrip("/")
        self.timeout = settings.opa_timeout_seconds
        self.decision_path = settings.policy_decision_path.strip("/")

    async def evaluate(self, opa_input: dict) -> PolicyDecision:
        import httpx

        url = f"{self.base_url}/v1/data/{self.decision_path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json={"input": opa_input})
        except Exception as exc:
            raise OPAError(f"OPA request failed: {exc}") from exc
        if response.status_code != 200:
            raise OPAError(f"OPA returned HTTP {response.status_code}: {response.text[:300]}")
        try:
            result = response.json()["result"]
        except (KeyError, ValueError) as exc:
            raise OPAError(f"OPA response malformed: {response.text[:300]}") from exc
        return PolicyDecision(
            decision=result.get("decision", "DENY"),
            deny=[PolicyFinding(**f) for f in result.get("deny", [])],
            approval_reasons=[PolicyFinding(**f) for f in result.get("approval_reasons", [])],
            evaluator="opa-server",
            evaluated_at=utcnow(),
        )

    async def health(self) -> bool:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except Exception:
            return False

    async def data_present(self) -> bool:
        """Verify the policy data actually loaded (guards against silent
        mount/path mistakes that would otherwise deny every run)."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/v1/data/approved/tools")
            if response.status_code != 200:
                return False
            result = response.json().get("result", [])
            return isinstance(result, list) and len(result) > 0
        except Exception:
            return False
