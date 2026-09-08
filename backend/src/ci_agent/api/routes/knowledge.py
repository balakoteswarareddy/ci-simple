"""Knowledge catalog endpoints (PDF §6): browse, ingest, refresh."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...config import Settings, get_settings
from ...knowledge.ingest import Ingester
from ...knowledge.store import KnowledgeStore
from ...llm.base import LLMClient
from ..deps import get_kstore, get_llm

router = APIRouter(tags=["knowledge"])


class IngestRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    hint_tool: str = ""
    hint_capabilities: list[str] = Field(default_factory=list)


class RefreshRequest(BaseModel):
    tools: list[str] | None = None


@router.get("/knowledge/tools")
async def list_tools(kstore: KnowledgeStore = Depends(get_kstore)) -> dict:
    return {"tools": kstore.all_tools()}


@router.get("/knowledge/stats")
async def knowledge_stats(kstore: KnowledgeStore = Depends(get_kstore)) -> dict:
    return kstore.stats()


@router.get("/knowledge/tools/{name}")
async def get_tool(name: str, kstore: KnowledgeStore = Depends(get_kstore)) -> dict:
    record = kstore.get(name)
    if record is None:
        raise KeyError(f"unknown tool '{name}'")
    return record.model_dump()


@router.post("/knowledge/ingest")
async def ingest_url(
    body: IngestRequest,
    kstore: KnowledgeStore = Depends(get_kstore),
    llm: LLMClient = Depends(get_llm),
    settings: Settings = Depends(get_settings),
) -> dict:
    ingester = Ingester(settings, kstore, llm if llm.name != "deterministic" else None)
    result = await ingester.ingest_url(body.url, body.hint_tool, body.hint_capabilities)
    return {"url": result.url, "ok": result.ok, "tool": result.tool,
            "errors": result.errors, "notes": result.notes}


@router.post("/knowledge/refresh")
async def refresh_tools(
    body: RefreshRequest,
    kstore: KnowledgeStore = Depends(get_kstore),
    llm: LLMClient = Depends(get_llm),
    settings: Settings = Depends(get_settings),
) -> dict:
    ingester = Ingester(settings, kstore, llm if llm.name != "deterministic" else None)
    results = await ingester.refresh(body.tools)
    return {"refreshed": [
        {"url": r.url, "ok": r.ok, "tool": r.tool, "errors": r.errors, "notes": r.notes}
        for r in results
    ]}
