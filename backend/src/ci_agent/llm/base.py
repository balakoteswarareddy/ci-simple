"""LLM client boundary (PDF §7: the model is powerful but boxed in).

Structured in / structured out, narrow functions only, no raw credentials in
context, no shell. Two implementations: Foundry/OpenAI when configured,
deterministic offline planner otherwise.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..common.models import UserIntent
from ..config import Settings


@dataclass
class LLMCallStats:
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd_estimate: float = 0.0


class LLMClient(ABC):
    name: str = "abstract"

    @abstractmethod
    async def parse_intent(self, request_text: str, repo_facts: str) -> tuple[UserIntent, LLMCallStats]:
        """Turn a natural-language CI request into a structured UserIntent."""

    @abstractmethod
    async def propose_repairs(self, failures: str, ir_summary: str) -> tuple[list[dict], LLMCallStats]:
        """Propose bounded IR patches for validation failures."""

    @abstractmethod
    async def extract_tool_facts(self, source_text: str, url: str) -> tuple[list[dict], LLMCallStats]:
        """Extract structured tool facts from a fetched documentation page."""


def get_llm_client(settings: Settings) -> LLMClient:
    from .fallback import DeterministicClient
    from .foundry import FoundryClient

    if settings.llm_configured:
        return FoundryClient(settings)
    return DeterministicClient(settings)
