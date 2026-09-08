"""Knowledge retrieval for planning (PDF §5 step 4).

Given requested capabilities + repo ecosystems, return the best-grounded
tool record per capability. Missing coverage is explicit — the planner must
never invent a tool to fill the gap (§15 hallucinations).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..common.models import KnowledgeRecord
from ..config import Settings
from .store import KnowledgeStore


@dataclass
class Retrieval:
    records: list[KnowledgeRecord] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def retrieve(
    capabilities: list[str],
    ecosystems: list[str],
    store: KnowledgeStore,
    settings: Settings,
    max_per_capability: int = 3,
) -> Retrieval:
    seen: set[str] = set()
    out = Retrieval()
    for cap in capabilities:
        matches = store.search(cap, ecosystems, limit=max_per_capability)
        if not matches:
            out.missing_capabilities.append(cap)
            out.notes.append(f"no known tool for capability '{cap}' on ecosystems {ecosystems or ['any']}")
            continue
        for record in matches:
            if record.tool in seen:
                continue
            seen.add(record.tool)
            out.records.append(record)
            if not store.is_fresh(record):
                origin = record.source.source_type if record.source else "unknown"
                out.notes.append(f"tool '{record.tool}' uses {origin} data — refresh recommended")
    return out
