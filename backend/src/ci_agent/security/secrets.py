"""Runtime secret access (PDF §10 secrets).

Secrets come from the environment or Docker-style *_FILE paths at runtime.
They are never logged, never embedded in prompts, and never persisted.
"""
from __future__ import annotations

import os
from pathlib import Path


class SecretStore:
    """Read-only secret accessor with *_FILE fallback (Docker secrets style)."""

    def get(self, name: str, default: str = "") -> str:
        direct = os.environ.get(name, "")
        if direct:
            return direct
        file_var = os.environ.get(f"{name}_FILE", "")
        if file_var:
            try:
                return Path(file_var).read_text(encoding="utf-8").strip()
            except OSError:
                return default
        return default

    def get_required(self, name: str) -> str:
        value = self.get(name)
        if not value:
            raise RuntimeError(f"required secret {name} (or {name}_FILE) is not set")
        return value

    def has(self, name: str) -> bool:
        return bool(self.get(name))


store = SecretStore()
