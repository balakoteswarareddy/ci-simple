"""Evidence + run persistence (PDF §4 evidence store, §10 audit).

Runs hold current state; events, approvals, and evidence versions are
append-only. Everything persisted passes through secret redaction.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import func

from ..common.db import (
    ApprovalRow,
    EventRow,
    EvidenceRow,
    RunRow,
    dumps,
    init_db,
    loads,
    session_scope,
)
from ..common.models import ApprovalRecord, DecisionEvidence, RunEvent, RunOptions, RunStatus
from ..common.util import new_id, utcnow
from ..config import Settings
from ..observability.logging import get_logger
from ..security.redact import redact, redact_obj

LOG = get_logger("ci_agent.evidence")

_RUN_JSON_FIELDS = {
    "options", "context", "intent", "plan", "policy", "ir", "validation",
    "security", "supply_chain", "publish", "costs",
}


class EvidenceStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        init_db(settings)

    # -- runs ------------------------------------------------------------
    def create_run(self, repo_url: str, request_text: str, options: RunOptions) -> str:
        run_id = new_id("run")
        with session_scope(self.settings) as session:
            session.add(RunRow(
                id=run_id, repo_url=repo_url, revision=options.revision,
                request_text=redact(request_text)[:8000], platform=options.platform,
                status=RunStatus.QUEUED.value, options_json=dumps(redact_obj(options.model_dump())),
            ))
        LOG.info("created run=%s repo=%s", run_id, redact(repo_url))
        return run_id

    def get_run(self, run_id: str) -> dict | None:
        with session_scope(self.settings) as session:
            row = session.get(RunRow, run_id)
            if row is None:
                return None
            return self._row_to_dict(row)

    def list_runs(self, limit: int = 50, status: str | None = None) -> list[dict]:
        with session_scope(self.settings) as session:
            query = session.query(RunRow).order_by(RunRow.created_at.desc())
            if status:
                query = query.filter(RunRow.status == status)
            return [self._row_summary(r) for r in query.limit(limit).all()]

    def update_run(self, run_id: str, **fields) -> None:
        with session_scope(self.settings) as session:
            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError(f"unknown run {run_id}")
            for key, value in fields.items():
                if key in _RUN_JSON_FIELDS:
                    setattr(row, f"{key}_json", dumps(redact_obj(value)))
                elif key in ("status", "current_step", "risk_level", "renderer",
                             "rendered_yaml", "explanation", "error", "revision"):
                    setattr(row, key, redact(str(value)) if isinstance(value, str) else value)
                elif key == "repair_attempts":
                    row.repair_attempts = int(value)
                else:
                    raise ValueError(f"unknown run field '{key}'")
            row.updated_at = utcnow()

    def _row_to_dict(self, row: RunRow) -> dict:
        return {
            "id": row.id, "repo_url": row.repo_url, "revision": row.revision,
            "request": row.request_text, "platform": row.platform, "status": row.status,
            "current_step": row.current_step, "risk_level": row.risk_level,
            "renderer": row.renderer, "rendered_yaml": row.rendered_yaml,
            "explanation": row.explanation, "error": row.error,
            "repair_attempts": row.repair_attempts,
            "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at),
            **{key: loads(getattr(row, f"{key}_json"), [] if key in ("validation", "costs") else {}) for key in _RUN_JSON_FIELDS},
        }

    def _row_summary(self, row: RunRow) -> dict:
        return {
            "id": row.id, "repo_url": row.repo_url, "platform": row.platform,
            "status": row.status, "current_step": row.current_step,
            "risk_level": row.risk_level, "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
            "request": row.request_text[:200],
        }

    # -- events ------------------------------------------------------------
    def append_event(self, run_id: str, step: str, level: str, message: str, data: dict | None = None) -> int:
        with session_scope(self.settings) as session:
            seq = (session.query(func.max(EventRow.seq)).filter(EventRow.run_id == run_id).scalar() or 0) + 1
            session.add(EventRow(
                run_id=run_id, seq=seq, step=step[:64], level=level[:16],
                message=redact(message)[:4000], data_json=dumps(redact_obj(data or {})),
            ))
            return seq

    def list_events(self, run_id: str, after_seq: int = 0, limit: int = 500) -> list[dict]:
        with session_scope(self.settings) as session:
            rows = (
                session.query(EventRow)
                .filter(EventRow.run_id == run_id, EventRow.seq > after_seq)
                .order_by(EventRow.seq.asc()).limit(limit).all()
            )
            return [
                {"seq": r.seq, "step": r.step, "level": r.level, "message": r.message,
                 "data": loads(r.data_json, {}), "created_at": _iso(r.created_at)}
                for r in rows
            ]

    # -- approvals -----------------------------------------------------------
    def save_approval(self, record: ApprovalRecord) -> None:
        with session_scope(self.settings) as session:
            session.add(ApprovalRow(
                run_id=record.run_id, approver=record.approver[:128],
                decision=record.decision, reason=redact(record.reason)[:2000],
            ))

    def get_approval(self, run_id: str) -> dict | None:
        with session_scope(self.settings) as session:
            row = (
                session.query(ApprovalRow).filter(ApprovalRow.run_id == run_id)
                .order_by(ApprovalRow.id.desc()).first()
            )
            if row is None:
                return None
            return {"run_id": row.run_id, "approver": row.approver,
                    "decision": row.decision, "reason": row.reason,
                    "decided_at": _iso(row.created_at)}

    def list_pending_approvals(self) -> list[dict]:
        return self.list_runs(limit=100, status=RunStatus.AWAITING_APPROVAL.value)

    # -- evidence -------------------------------------------------------------
    def save_evidence(self, evidence: DecisionEvidence) -> int:
        with session_scope(self.settings) as session:
            version = (session.query(func.max(EvidenceRow.version))
                       .filter(EvidenceRow.run_id == evidence.run_id).scalar() or 0) + 1
            session.add(EvidenceRow(
                run_id=evidence.run_id, version=version,
                evidence_json=dumps(redact_obj(evidence.model_dump())),
                evidence_hash=evidence.evidence_hash,
            ))
            return version

    def get_evidence(self, run_id: str) -> dict | None:
        with session_scope(self.settings) as session:
            row = (
                session.query(EvidenceRow).filter(EvidenceRow.run_id == run_id)
                .order_by(EvidenceRow.version.desc()).first()
            )
            if row is None:
                return None
            payload = loads(row.evidence_json, {})
            payload["_version"] = row.version
            return payload

    # -- artifacts --------------------------------------------------------------
    def artifact_dir(self, run_id: str) -> Path:
        path = self.settings.resolved_data_dir / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_artifact(self, run_id: str, name: str, content: str) -> Path:
        dest = self.artifact_dir(run_id) / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        return dest


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        from datetime import timezone

        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def event_model(run_id: str, seq: int, step: str, level: str, message: str, data: dict | None = None) -> RunEvent:
    return RunEvent(run_id=run_id, seq=seq, step=step, level=level, message=message, data=data or {})
