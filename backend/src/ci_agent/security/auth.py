"""API authentication (Phase 0 skeleton, §10 identity).

If CI_AGENT_API_KEY is set, every /api/v1 route requires it via X-API-Key.
Health/readiness stay public for orchestrators. Approver identity is taken
from X-Actor (reverse proxy / IdP should set this in production).
"""
from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException, status

from ..config import Settings, get_settings

_logged_open_warning = False


async def require_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    global _logged_open_warning
    expected = settings.api_key
    if not expected:
        if not _logged_open_warning:
            _logged_open_warning = True
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing API key")


async def get_actor(x_actor: str | None = Header(default=None)) -> str:
    return (x_actor or "unknown").strip()[:128] or "unknown"
