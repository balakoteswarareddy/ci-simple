"""Shared pytest fixtures: isolated settings/DB per test, seeded knowledge."""
from __future__ import annotations

from pathlib import Path

import pytest

from ci_agent.common import db as db_module
from ci_agent.config import Settings, reset_settings
from ci_agent.evidence.store import EvidenceStore
from ci_agent.knowledge.store import KnowledgeStore
from ci_agent.policy.catalog import get_catalog, reset_catalog_cache

REPO_ROOT = Path(__file__).resolve().parents[2]
OPA_STORE = REPO_ROOT / "deploy" / "opa" / "store"
FIXTURES = Path(__file__).parent / "fixtures" / "repos"


@pytest.fixture()
def tmp_settings(tmp_path):
    db_module.reset_engine()
    reset_settings()
    reset_catalog_cache()
    settings = Settings(
        DATABASE_URL=f"sqlite:///{tmp_path}/test.db",
        CI_AGENT_DATA_DIR=str(tmp_path / "data"),
        AGENT_WORK_DIR=str(tmp_path / "work"),
        OPA_BUNDLE_DIR=str(OPA_STORE),
        ALLOW_LOCAL_REPOS=True,
    )
    yield settings
    db_module.reset_engine()
    reset_settings()
    reset_catalog_cache()


@pytest.fixture()
def estore(tmp_settings) -> EvidenceStore:
    return EvidenceStore(tmp_settings)


@pytest.fixture()
def kstore(tmp_settings) -> KnowledgeStore:
    store = KnowledgeStore(tmp_settings)
    store.ensure_seeded()
    return store


@pytest.fixture()
def catalog(tmp_settings):
    return get_catalog(tmp_settings)


@pytest.fixture()
def sample_python() -> Path:
    return FIXTURES / "sample-python"


@pytest.fixture()
def sample_node() -> Path:
    return FIXTURES / "sample-node"


@pytest.fixture()
def injection_repo() -> Path:
    return FIXTURES / "injection-repo"
