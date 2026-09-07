"""Small shared helpers: ids, time, hashing, path safety."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat()


def new_id(prefix: str = "") -> str:
    token = uuid.uuid4().hex[:12]
    return f"{prefix}_{token}" if prefix else token


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(obj: Any) -> str:
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return sha256_text(canonical)


def truncate(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"


def safe_join(root: Path, *parts: str) -> Path:
    """Join untrusted path parts onto root, rejecting path traversal."""
    root = root.resolve()
    candidate = (root.joinpath(*parts)).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path escapes workspace root: {'/'.join(parts)}")
    return candidate


def ensure_within(root: Path, candidate: Path) -> Path:
    root_r = root.resolve()
    cand_r = candidate.resolve()
    if cand_r != root_r and root_r not in cand_r.parents:
        raise ValueError(f"path escapes workspace root: {candidate}")
    return cand_r
