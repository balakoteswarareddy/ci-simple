"""Structured logging (PDF §4 observability, §10 audit).

JSON logs in production, human-readable text in dev. All records pass through
secret redaction. Request/run/step ids travel via contextvars.
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from contextvars import ContextVar
from typing import Any

from ..security.redact import redact

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_run_id: ContextVar[str] = ContextVar("run_id", default="-")


def set_request_id(value: str) -> None:
    _request_id.set(value or "-")


def set_run_id(value: str) -> None:
    _run_id.set(value or "-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
            "request_id": _request_id.get(),
            "run_id": _run_id.get(),
        }
        if record.exc_info:
            payload["exc"] = redact("".join(traceback.format_exception(*record.exc_info))[-4000:])
        for key in ("step", "repo", "tool", "validator", "model"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        return redact(base)


_configured = False


def setup_logging(level: str = "INFO", fmt: str = "json") -> None:
    global _configured
    if _configured:
        return
    _configured = True
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "text":
        handler.setFormatter(TextFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    else:
        handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
