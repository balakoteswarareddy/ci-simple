"""Normalized knowledge store (PDF §6): canonical tool/capability records
with evidence + freshness. Seeds bootstrap the store; ingestion refreshes it.

Dedup rule (§6.2 step 7): one row per canonical tool name; sources merge,
evidence accumulates, newest retrieval wins for versions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..common.db import KnowledgeRow, dumps, init_db, loads, session_scope
from ..common.models import KnowledgeRecord, KnowledgeSource
from ..common.util import utcnow
from ..config import Settings
from ..observability.logging import get_logger
from ..observability.metrics import KNOWLEDGE_RECORDS

LOG = get_logger("ci_agent.knowledge")


class KnowledgeStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        init_db(settings)

    # -- lifecycle ----------------------------------------------------
    def ensure_seeded(self) -> int:
        """Insert curated seeds iff the store is empty. Returns row count."""
        from .seeds import load_seed_records

        with session_scope(self.settings) as session:
            count = session.query(KnowledgeRow).count()
            if count > 0:
                KNOWLEDGE_RECORDS.set(count)
                return count
            seeds = load_seed_records()
            for record in seeds:
                session.add(KnowledgeRow(tool=record.tool, record_json=dumps(record.model_dump())))
            LOG.info("seeded knowledge store with %d records", len(seeds))
            KNOWLEDGE_RECORDS.set(len(seeds))
            return len(seeds)

    # -- reads ----------------------------------------------------------
    def get(self, tool: str) -> KnowledgeRecord | None:
        with session_scope(self.settings) as session:
            row = session.get(KnowledgeRow, tool.strip().lower())
            if row is None:
                return None
            return KnowledgeRecord(**loads(row.record_json))

    def all_tools(self) -> list[str]:
        with session_scope(self.settings) as session:
            rows = session.query(KnowledgeRow.tool).order_by(KnowledgeRow.tool).all()
            return [r[0] for r in rows]

    def search(self, capability: str, ecosystems: list[str], limit: int = 5) -> list[KnowledgeRecord]:
        """Rank records for a capability: ecosystem overlap, then freshness,
        then confidence. Stale records are returned but flagged by callers."""
        capability = capability.strip().lower()
        ecos = {e.strip().lower() for e in ecosystems}
        candidates: list[tuple[float, KnowledgeRecord]] = []
        for tool in self.all_tools():
            record = self.get(tool)
            if record is None:
                continue
            caps = {c.lower() for c in record.capabilities}
            if capability not in caps and "any" not in caps:
                continue
            rec_ecos = {e.lower() for e in record.ecosystems}
            eco_score = 2.0 if (rec_ecos & ecos) else (1.0 if "any" in rec_ecos or not rec_ecos else 0.0)
            if eco_score == 0.0:
                continue
            fresh = 1.0 if self.is_fresh(record) else 0.0
            score = eco_score * 10 + fresh * 5 + record.confidence
            candidates.append((score, record))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in candidates[:limit]]

    def is_fresh(self, record: KnowledgeRecord) -> bool:
        if record.source is None or record.source.source_type == "curated-seed":
            return False
        ttl = timedelta(hours=self.settings.knowledge_cache_ttl_hours)
        retrieved = record.source.retrieved_at
        if retrieved.tzinfo is None:
            retrieved = retrieved.replace(tzinfo=timezone.utc)
        return utcnow() - retrieved < ttl

    # -- writes ----------------------------------------------------------
    def upsert(self, record: KnowledgeRecord) -> KnowledgeRecord:
        """Merge a record into the canonical row (§6.2 step 7)."""
        record.tool = record.tool.strip().lower()
        if not record.tool:
            raise ValueError("cannot store a tool record without a name")
        merged = record
        existing = self.get(record.tool)
        if existing is not None:
            merged = self._merge(existing, record)
        merged.record_hash = merged.compute_hash()
        with session_scope(self.settings) as session:
            row = session.get(KnowledgeRow, merged.tool)
            payload = dumps(merged.model_dump())
            if row is None:
                session.add(KnowledgeRow(tool=merged.tool, record_json=payload))
            else:
                row.record_json = payload
                row.updated_at = utcnow()
        LOG.info("upserted knowledge record tool=%s", merged.tool)
        return merged

    def _merge(self, old: KnowledgeRecord, new: KnowledgeRecord) -> KnowledgeRecord:
        capabilities = sorted(set(old.capabilities) | set(new.capabilities))
        ecosystems = sorted(set(old.ecosystems) | set(new.ecosystems))
        ci = sorted(set(old.ci_integrations) | set(new.ci_integrations))
        installs = {(i.type, i.command) for i in old.install_methods} | {(i.type, i.command) for i in new.install_methods}
        versions = list(dict.fromkeys([*new.versions, *old.versions]))[:8]
        evidence_old = old.source.evidence if old.source else []
        evidence_new = new.source.evidence if new.source else []
        evidence = list(dict.fromkeys([*evidence_new, *evidence_old]))[:12]
        source = new.source or old.source
        if source is not None:
            source = KnowledgeSource(
                url=source.url,
                source_type=source.source_type,
                retrieved_at=new.source.retrieved_at if new.source else source.retrieved_at,
                evidence=evidence,
            )
        return KnowledgeRecord(
            tool=new.tool,
            capabilities=capabilities,
            ecosystems=ecosystems,
            install_methods=[{"type": t, "command": c} for t, c in sorted(installs)],  # type: ignore[list-item]
            ci_integrations=ci,
            versions=versions,
            source=source,
            confidence=max(old.confidence, new.confidence),
        )

    # -- snapshots (golden tests / export) -------------------------------
    def snapshot(self) -> list[dict]:
        with session_scope(self.settings) as session:
            rows = session.query(KnowledgeRow).order_by(KnowledgeRow.tool).all()
            return [loads(r.record_json) for r in rows]

    def load_snapshot(self, records: list[dict]) -> int:
        from .schemas import validate_tool_fact

        count = 0
        for item in records:
            data = dict(item)
            data.pop("record_hash", None)
            source = data.get("source") or {}
            payload = {
                "tool": data.get("tool", ""),
                "capabilities": data.get("capabilities", []),
                "ecosystems": data.get("ecosystems", []),
                "install_methods": data.get("install_methods", []),
                "ci_integrations": data.get("ci_integrations", []),
                "versions": data.get("versions", []),
                "evidence": source.get("evidence", []) if isinstance(source, dict) else [],
                "confidence": data.get("confidence", 0.5),
            }
            validate_tool_fact(payload)
            record = KnowledgeRecord(**data)
            record.record_hash = record.compute_hash()
            with session_scope(self.settings) as session:
                row = session.get(KnowledgeRow, record.tool)
                blob = dumps(record.model_dump())
                if row is None:
                    session.add(KnowledgeRow(tool=record.tool, record_json=blob))
                else:
                    row.record_json = blob
                    row.updated_at = utcnow()
            count += 1
        return count

    def stats(self) -> dict:
        tools = self.all_tools()
        cap_count: dict[str, int] = {}
        seeds = fresh = 0
        for tool in tools:
            record = self.get(tool)
            if record is None:
                continue
            for cap in record.capabilities:
                cap_count[cap] = cap_count.get(cap, 0) + 1
            if record.source and record.source.source_type == "curated-seed":
                seeds += 1
            if self.is_fresh(record):
                fresh += 1
        return {"tools": len(tools), "capabilities": cap_count, "seed_records": seeds, "fresh_records": fresh}
