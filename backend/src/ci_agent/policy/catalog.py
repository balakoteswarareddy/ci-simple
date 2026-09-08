"""Policy catalog reader. The JSON files under OPA_BUNDLE_DIR are the single
source of truth shared by the OPA server and the Python planner/validators —
change them once, both sides agree."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..config import Settings


@dataclass
class PolicyCatalog:
    tools: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    action_prefixes: list[str] = field(default_factory=list)
    denied_licenses: list[str] = field(default_factory=list)
    protected_branches: list[str] = field(default_factory=list)
    allow_unpinned: bool = False
    never_write: list[str] = field(default_factory=list)
    known_permissions: list[str] = field(default_factory=list)
    max_repair_attempts: int = 3
    bundle_dir: str = ""


def _read_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


@lru_cache(maxsize=4)
def _load_cached(bundle_dir: str) -> PolicyCatalog:
    root = Path(bundle_dir)
    # Single data.json: OPA merges a root-level data.json at the data root,
    # so {"approved":...} is addressable as data.approved on the server and
    # readable here without any path-mapping ambiguity.
    bundle = _read_json(root / "data.json", {})
    approved = bundle.get("approved", {})
    denied = bundle.get("denied", {})
    limits = bundle.get("limits", {})
    return PolicyCatalog(
        tools=list(approved.get("tools", [])),
        capabilities=list(approved.get("capabilities", [])),
        action_prefixes=list(approved.get("actions", [])),
        denied_licenses=list(denied.get("licenses", [])),
        protected_branches=list(limits.get("protected_branches", ["main", "master"])),
        allow_unpinned=bool(limits.get("allow_unpinned", False)),
        never_write=list(limits.get("never_write", [])),
        known_permissions=list(limits.get("known_permissions", [])),
        max_repair_attempts=int(limits.get("max_repair_attempts", 3)),
        bundle_dir=bundle_dir,
    )


def get_catalog(settings: Settings) -> PolicyCatalog:
    return _load_cached(settings.opa_bundle_dir)


def reset_catalog_cache() -> None:
    _load_cached.cache_clear()
