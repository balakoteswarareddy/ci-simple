"""Shared FastAPI dependencies (wired per request, engines cached)."""
from __future__ import annotations

from fastapi import Depends

from ..agent.orchestrator import Orchestrator
from ..config import Settings, get_settings
from ..evidence.store import EvidenceStore
from ..knowledge.store import KnowledgeStore
from ..llm.base import LLMClient, get_llm_client


def get_store(settings: Settings = Depends(get_settings)) -> EvidenceStore:
    return EvidenceStore(settings)


def get_kstore(settings: Settings = Depends(get_settings)) -> KnowledgeStore:
    store = KnowledgeStore(settings)
    store.ensure_seeded()
    return store


def get_llm(settings: Settings = Depends(get_settings)) -> LLMClient:
    return get_llm_client(settings)


def get_orchestrator(
    settings: Settings = Depends(get_settings),
    store: EvidenceStore = Depends(get_store),
    kstore: KnowledgeStore = Depends(get_kstore),
    llm: LLMClient = Depends(get_llm),
) -> Orchestrator:
    return Orchestrator(settings, store=store, kstore=kstore, llm=llm)
