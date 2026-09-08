"""Persistence layer. SQLite by default (local dev/tests), Postgres in compose.

Tables are append-friendly: runs hold current state, events/approvals/evidence
are append-only audit history. Artifacts (YAML, SBOM) live on disk under the
data dir; the DB stores paths + hashes.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from ..config import Settings


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo_url: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[str] = mapped_column(String(128), default="")
    request_text: Mapped[str] = mapped_column(Text, default="")
    platform: Mapped[str] = mapped_column(String(32), default="github")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    current_step: Mapped[str] = mapped_column(String(64), default="")
    options_json: Mapped[str] = mapped_column(Text, default="{}")
    context_json: Mapped[str] = mapped_column(Text, default="{}")
    intent_json: Mapped[str] = mapped_column(Text, default="{}")
    plan_json: Mapped[str] = mapped_column(Text, default="{}")
    policy_json: Mapped[str] = mapped_column(Text, default="{}")
    risk_level: Mapped[str] = mapped_column(String(16), default="low")
    ir_json: Mapped[str] = mapped_column(Text, default="{}")
    rendered_yaml: Mapped[str] = mapped_column(Text, default="")
    renderer: Mapped[str] = mapped_column(String(32), default="")
    validation_json: Mapped[str] = mapped_column(Text, default="[]")
    security_json: Mapped[str] = mapped_column(Text, default="{}")
    supply_chain_json: Mapped[str] = mapped_column(Text, default="{}")
    publish_json: Mapped[str] = mapped_column(Text, default="{}")
    costs_json: Mapped[str] = mapped_column(Text, default="[]")
    explanation: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    repair_attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class EventRow(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    seq: Mapped[int] = mapped_column(default=0)
    step: Mapped[str] = mapped_column(String(64), default="")
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text, default="")
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (Index("ix_events_run_seq", "run_id", "seq"),)


class ApprovalRow(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    approver: Mapped[str] = mapped_column(String(128), default="unknown")
    decision: Mapped[str] = mapped_column(String(16), default="approve")
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class EvidenceRow(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    version: Mapped[int] = mapped_column(default=1)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class KnowledgeRow(Base):
    __tablename__ = "knowledge"

    tool: Mapped[str] = mapped_column(String(128), primary_key=True)
    record_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


_engine = None
_session_factory = None


def _sqlite_path(url: str) -> Path | None:
    prefix = "sqlite:///"
    if url.startswith(prefix):
        return Path(url[len(prefix):])
    return None


def get_engine(settings: Settings):
    global _engine
    if _engine is not None:
        return _engine
    url = settings.database_url
    kwargs: dict[str, Any] = {"future": True}
    if url.startswith("sqlite:"):
        kwargs["connect_args"] = {"check_same_thread": False}
        p = _sqlite_path(url)
        if p and str(p) != ":memory:":
            p.parent.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(url, **kwargs)
    return _engine


def get_session_factory(settings: Settings) -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(settings), expire_on_commit=False)
    return _session_factory


def reset_engine() -> None:
    """Tests only: drop cached engine/session so a new DATABASE_URL applies."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def init_db(settings: Settings) -> None:
    Base.metadata.create_all(get_engine(settings))


@contextmanager
def session_scope(settings: Settings) -> Iterator[Session]:
    factory = get_session_factory(settings)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=str, separators=(",", ":"))


def loads(text: str | None, default: Any = None) -> Any:
    if not text:
        return default if default is not None else {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default if default is not None else {}
