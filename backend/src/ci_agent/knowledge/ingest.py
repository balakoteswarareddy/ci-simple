"""Knowledge ingestion flow (PDF §6.2 steps 1-7).

Fetch trusted sources -> treat content as UNTRUSTED data -> extract structured
facts (LLM or heuristic) -> schema-validate -> rule-check claims against the
source text -> dedup/merge into the store with evidence + freshness.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from ..common.models import KnowledgeRecord, KnowledgeSource, ToolInstall
from ..common.util import truncate, utcnow
from ..config import Settings
from ..observability.logging import get_logger
from .schemas import validate_tool_fact
from .store import KnowledgeStore

LOG = get_logger("ci_agent.knowledge.ingest")

MAX_FETCH_BYTES = 512 * 1024
MAX_EXTRACT_CHARS = 24000


@dataclass
class FetchedContent:
    url: str
    status_code: int
    text: str
    content_type: str = ""


@dataclass
class IngestResult:
    url: str
    ok: bool
    tool: str = ""
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def html_to_text(markup: str) -> str:
    """Best-effort HTML -> text. Never executes anything; output is data."""
    cleaned = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", markup)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    return re.sub(r"\s+", " ", html.unescape(cleaned)).strip()


class Ingester:
    def __init__(self, settings: Settings, store: KnowledgeStore, llm=None):
        self.settings = settings
        self.store = store
        self.llm = llm

    # -- fetch ---------------------------------------------------------
    def _host_allowed(self, url: str) -> bool:
        try:
            host = (urlparse(url).hostname or "").lower()
        except ValueError:
            return False
        return any(host == allowed or host.endswith("." + allowed) for allowed in self.settings.knowledge_allow_hosts_list)

    async def fetch(self, url: str) -> FetchedContent:
        if not url.startswith("https://"):
            raise ValueError(f"refusing to fetch non-https URL: {url[:80]}")
        if not self._host_allowed(url):
            raise ValueError(f"host not in KNOWLEDGE_ALLOW_HOSTS: {url[:80]}")
        timeout = self.settings.knowledge_fetch_timeout_seconds
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, max_redirects=3) as client:
            response = await client.get(url, headers={"User-Agent": "ci-agent-knowledge/0.1"})
        body = response.content[:MAX_FETCH_BYTES]
        content_type = response.headers.get("content-type", "")
        try:
            raw = body.decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        text = html_to_text(raw) if "html" in content_type or "<html" in raw[:2000].lower() else raw
        LOG.info("fetched knowledge url=%s status=%d chars=%d", url, response.status_code, len(text))
        return FetchedContent(url=url, status_code=response.status_code, text=text, content_type=content_type)

    # -- ingest ---------------------------------------------------------
    async def ingest_url(
        self,
        url: str,
        hint_tool: str = "",
        hint_capabilities: list[str] | None = None,
    ) -> IngestResult:
        result = IngestResult(url=url, ok=False)
        try:
            fetched = await self.fetch(url)
        except Exception as exc:
            result.errors.append(str(exc))
            return result
        if fetched.status_code >= 400 or not fetched.text.strip():
            result.errors.append(f"fetch failed with status {fetched.status_code}")
            return result

        facts: list[dict] = []
        if self.llm is not None:
            try:
                facts = await self.llm.extract_tool_facts(truncate(fetched.text, MAX_EXTRACT_CHARS), url)
            except Exception as exc:
                result.notes.append(f"llm extraction failed, heuristic fallback used: {exc}")
        if not facts:
            facts = [self._heuristic_fact(fetched.text, url, hint_tool, hint_capabilities or [])]

        stored = 0
        for fact in facts:
            try:
                validate_tool_fact(fact)
            except Exception as exc:
                result.errors.append(f"schema validation rejected fact: {exc}")
                continue
            # Rule-based claim check (§6.2 step 5): drop versions the source
            # never mentions instead of storing unverified claims.
            fact, dropped = self._check_claims(fact, fetched.text)
            if dropped:
                result.notes.append(f"dropped unverified versions for '{fact['tool']}': {dropped}")
                fact["confidence"] = min(float(fact.get("confidence", 0.5)), 0.4)
            record = KnowledgeRecord(
                tool=fact["tool"],
                capabilities=fact.get("capabilities", []),
                ecosystems=fact.get("ecosystems", []),
                install_methods=[ToolInstall(**i) for i in fact.get("install_methods", [])],
                ci_integrations=fact.get("ci_integrations", []),
                versions=fact.get("versions", []),
                source=KnowledgeSource(
                    url=url, source_type="doc_page",
                    retrieved_at=utcnow(), evidence=fact.get("evidence", [])[:10],
                ),
                confidence=float(fact.get("confidence", 0.5)),
            )
            self.store.upsert(record)
            stored += 1
            result.tool = record.tool
        result.ok = stored > 0
        if stored == 0 and not result.errors:
            result.errors.append("no usable facts extracted")
        return result

    async def refresh(self, tools: list[str] | None = None) -> list[IngestResult]:
        """Re-fetch official sources for seed/known records to fight staleness
        (PDF §15 stale knowledge)."""
        names = tools or self.store.all_tools()
        results: list[IngestResult] = []
        for name in names:
            record = self.store.get(name)
            if record is None or record.source is None:
                continue
            if self.store.is_fresh(record):
                continue
            res = await self.ingest_url(
                record.source.url, hint_tool=record.tool, hint_capabilities=record.capabilities
            )
            results.append(res)
        return results

    # -- extraction helpers ----------------------------------------------
    def _heuristic_fact(self, text: str, url: str, hint_tool: str, hint_caps: list[str]) -> dict:
        title = ""
        m = re.search(r"(.{0,120}?)", text.strip())
        if m:
            title = m.group(1).strip()
        return {
            "tool": (hint_tool or urlparse(url).path.strip("/").split("/")[-1] or "unknown").lower()[:128],
            "capabilities": hint_caps,
            "ecosystems": [],
            "install_methods": [],
            "ci_integrations": [],
            "versions": [],
            "evidence": [truncate(title, 300)] if title else [],
            "confidence": 0.2,
        }

    def _check_claims(self, fact: dict, source_text: str) -> tuple[dict, list[str]]:
        lowered = source_text.lower()
        kept, dropped = [], []
        for version in fact.get("versions", []):
            needle = str(version).strip().lower()
            if not needle or needle in ("bundled",):
                kept.append(version)
            elif needle in lowered:
                kept.append(version)
            else:
                dropped.append(version)
        fact["versions"] = kept
        return fact, dropped
