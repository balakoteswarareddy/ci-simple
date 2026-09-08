"""CI Agent REST API (PDF §4 api module, §12).

Public: /healthz, /readyz. Everything under /api/v1 requires X-API-Key when
CI_AGENT_API_KEY is set. Prometheus metrics at /metrics.
"""
from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .. import __version__
from ..config import get_settings
from ..observability.logging import get_logger, set_request_id, setup_logging
from ..observability.metrics import metrics_response
from ..security.auth import require_api_key
from .routes import approvals, knowledge, policies, runs

LOG = get_logger("ci_agent.api")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", "") or uuid.uuid4().hex[:12]
        set_request_id(request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title="CI Agent",
        description="Evidence-driven AI CI agent: repo intelligence, grounded planning, OPA governance.",
        version=__version__,
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(KeyError)
    async def _not_found(_: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def _bad_request(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", tags=["ops"])
    async def readyz() -> dict:
        from ..evidence.store import EvidenceStore
        from ..knowledge.store import KnowledgeStore
        from ..policy.opa import OPAClient

        checks: dict[str, dict] = {}
        ready = True
        try:
            EvidenceStore(settings).list_runs(limit=1)
            checks["database"] = {"ok": True}
        except Exception as exc:
            ready = False
            checks["database"] = {"ok": False, "error": str(exc)[:200]}
        if settings.opa_url:
            opa = OPAClient(settings)
            healthy = await opa.health()
            data_ok = await opa.data_present() if healthy else False
            checks["opa"] = {"ok": healthy and data_ok, "mode": "server",
                             "url": settings.opa_url, "data_loaded": data_ok}
            ready = ready and healthy and data_ok
        else:
            checks["opa"] = {"ok": True, "mode": "local-mirror",
                             "warning": "OPA_URL unset — dev/test only"}
        try:
            count = KnowledgeStore(settings).ensure_seeded()
            checks["knowledge"] = {"ok": True, "records": count}
        except Exception as exc:
            ready = False
            checks["knowledge"] = {"ok": False, "error": str(exc)[:200]}
        checks["llm"] = {"ok": True, "provider": settings.effective_llm_provider,
                         "model": settings.llm_model_name if settings.llm_configured else "deterministic-fallback"}
        return {"ready": ready, "checks": checks}

    @app.get("/metrics", tags=["ops"])
    async def metrics() -> Response:
        if not settings.metrics_enabled:
            return JSONResponse(status_code=404, content={"detail": "metrics disabled"})
        body, content_type = metrics_response()
        return Response(content=body, media_type=content_type)

    guarded = [Depends(require_api_key)]
    app.include_router(runs.router, prefix="/api/v1", dependencies=guarded)
    app.include_router(approvals.router, prefix="/api/v1", dependencies=guarded)
    app.include_router(knowledge.router, prefix="/api/v1", dependencies=guarded)
    app.include_router(policies.router, prefix="/api/v1", dependencies=guarded)
    return app


app = create_app()
