"""Curated seed catalog (PDF §6.1 organization-owned catalog bootstrap).

Seeds are starting points with official-doc URLs as evidence — NOT the
long-term source of truth. The ingestion flow (§6.2) refreshes them into
first-class records with retrieval timestamps.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from ..common.models import KnowledgeRecord

SEED_PATH = Path(__file__).parent / "data" / "seed_tools.json"


def load_seed_records() -> list[KnowledgeRecord]:
    raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    records = [KnowledgeRecord(**item) for item in raw]
    for record in records:
        record.record_hash = record.compute_hash()
    return records


def seed_stats() -> dict:
    records = load_seed_records()
    caps: Counter[str] = Counter()
    for record in records:
        caps.update(record.capabilities)
    return {
        "seed_file": str(SEED_PATH),
        "tools": len(records),
        "capabilities": dict(sorted(caps.items())),
    }


def main() -> None:
    if "--stats" in sys.argv or "-s" in sys.argv:
        print(json.dumps(seed_stats(), indent=2))
    else:
        for record in load_seed_records():
            print(f"{record.tool:12s} {','.join(record.capabilities):28s} {record.source.url if record.source else ''}")


if __name__ == "__main__":
    main()
