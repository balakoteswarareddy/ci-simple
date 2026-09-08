"""Approval queue endpoint (governance)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ...evidence.store import EvidenceStore
from ..deps import get_store

router = APIRouter(tags=["approvals"])


@router.get("/approvals/pending")
async def pending_approvals(store: EvidenceStore = Depends(get_store)) -> dict:
    runs = store.list_pending_approvals()
    enriched = []
    for summary in runs:
        full = store.get_run(summary["id"]) or {}
        enriched.append({
            **summary,
            "policy": full.get("policy", {}),
            "risk_reasons": (full.get("publish") or {}),
        })
    return {"pending": enriched}
