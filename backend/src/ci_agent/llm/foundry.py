"""Azure AI Foundry / OpenAI client with schema-constrained outputs.

PDF §5 step 5 + §7: Structured Outputs so responses are machine-checkable,
one corrective retry on schema failure, then an explicit error (the caller
falls back deterministically and records it — never silent).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import jsonschema

from ..common.models import UserIntent
from ..common.util import truncate
from ..config import Settings
from ..knowledge.schemas import TOOL_FACT_LIST_SCHEMA
from ..observability.logging import get_logger
from ..security.redact import redact
from .base import LLMCallStats, LLMClient
from .schemas import INTENT_JSON_SCHEMA, REPAIR_JSON_SCHEMA

LOG = get_logger("ci_agent.llm")

INTENT_SYSTEM = """You parse CI requests into structured intent. Rules:
- platform: one of github, azure, gitlab, jenkins (default github).
- capabilities: only from [lint, format, test, sast, sca, secrets, container-scan, iac-scan, build, docker-build, sbom, sign, deploy].
  Map "security checks/scanning" to [sast, sca, secrets]; "full/complete/production CI" adds [lint, test, sast, sca, secrets].
- prohibited_tools: tools the user explicitly excludes ("don't use X", "no X", "without X"). Lowercase names only.
- deployment_target: production/staging/etc only if deployment is requested, else "".
- Never invent capabilities or tools. Output JSON only, matching the schema."""

REPAIR_SYSTEM = """You fix CI validation failures with minimal IR patches. Rules:
- Only use the allowed repair actions; target existing job_id/step_id values.
- Prefer pinning actions to known versions and least-privilege permissions.
- Never introduce new tools, URLs, or shell pipelines. JSON only."""

EXTRACT_SYSTEM = """You extract tool facts from documentation text. Rules:
- Only state what the text supports. versions: list ONLY versions explicitly mentioned; else [].
- capabilities from [lint, format, test, sast, sca, secrets, container-scan, iac-scan, build, docker-build, sbom, sign, deploy].
- evidence: short quotes (<=200 chars) supporting each fact. JSON only."""

# USD per 1M tokens (input, output). Unknown models use the default row.
COST_PER_MTOKENS: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "default": (1.00, 3.00),
}


class FoundryClient(LLMClient):
    name = "foundry"

    def __init__(self, settings: Settings):
        self.settings = settings
        provider = settings.effective_llm_provider
        if provider == "azure-foundry":
            from openai import AzureOpenAI

            self.client = AzureOpenAI(
                api_key=settings.foundry_api_key,
                azure_endpoint=settings.foundry_endpoint,
                api_version=settings.foundry_api_version,
            )
            self.model = settings.foundry_deployment
            self.provider = "azure-foundry"
        elif provider == "openai":
            from openai import OpenAI

            self.client = OpenAI(api_key=settings.openai_api_key)
            self.model = settings.openai_model
            self.provider = "openai"
        else:
            raise RuntimeError("no LLM provider configured")

    # -- core ----------------------------------------------------------
    async def _chat_json(
        self, system: str, user: str, schema: dict[str, Any], schema_name: str
    ) -> tuple[dict[str, Any], LLMCallStats]:
        user = redact(truncate(user, 12000))
        last_error = ""
        stats = LLMCallStats(model=f"{self.provider}:{self.model}")
        for attempt in range(2):
            prompt = user if attempt == 0 else f"{user}\n\nPrevious output failed validation: {last_error}. Fix it."
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "schema": schema, "strict": False},
                },
                temperature=self.settings.llm_temperature,
                max_tokens=self.settings.llm_max_tokens,
            )
            usage = response.usage
            if usage is not None:
                stats.input_tokens += usage.prompt_tokens or 0
                stats.output_tokens += usage.completion_tokens or 0
            content = (response.choices[0].message.content or "").strip()
            try:
                payload = json.loads(content)
                jsonschema.validate(payload, schema)
                stats.cost_usd_estimate = self._estimate(stats.input_tokens, stats.output_tokens)
                return payload, stats
            except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
                last_error = truncate(str(exc), 300)
                LOG.warning("llm schema validation failed attempt=%d err=%s", attempt, last_error)
        raise RuntimeError(f"LLM output failed schema validation: {last_error}")

    def _estimate(self, in_tokens: int, out_tokens: int) -> float:
        key = next((k for k in COST_PER_MTOKENS if k in self.model), "default")
        in_rate, out_rate = COST_PER_MTOKENS[key]
        return in_tokens / 1e6 * in_rate + out_tokens / 1e6 * out_rate

    # -- interface -------------------------------------------------------
    async def parse_intent(self, request_text: str, repo_facts: str) -> tuple[UserIntent, LLMCallStats]:
        payload, stats = await self._chat_json(
            INTENT_SYSTEM,
            f"Repository facts:\n{repo_facts}\n\nRequest:\n{request_text}",
            INTENT_JSON_SCHEMA,
            "ci_intent",
        )
        intent = UserIntent(**payload)
        intent.raw_request = truncate(request_text, 2000)
        intent.planner = f"{self.provider}:{self.model}"
        return intent, stats

    async def propose_repairs(self, failures: str, ir_summary: str) -> tuple[list[dict], LLMCallStats]:
        payload, stats = await self._chat_json(
            REPAIR_SYSTEM,
            f"Validation failures:\n{failures}\n\nPipeline IR summary:\n{ir_summary}",
            REPAIR_JSON_SCHEMA,
            "ci_repairs",
        )
        return payload.get("repairs", []), stats

    async def extract_tool_facts(self, source_text: str, url: str) -> tuple[list[dict], LLMCallStats]:
        payload, stats = await self._chat_json(
            EXTRACT_SYSTEM,
            f"Source URL: {url}\n\nDocumentation text:\n{truncate(source_text, 20000)}",
            TOOL_FACT_LIST_SCHEMA,
            "tool_facts",
        )
        return payload.get("tools", []), stats
