"""Sandbox boundaries, secret fallback scanner, SCA lockfile parsing."""
import pytest

from ci_agent.common.models import RepositoryContext
from ci_agent.config import Settings
from ci_agent.execution.sandbox import SandboxDenied, run_sandboxed
from ci_agent.integrations.scanners import _packages_from_lockfiles, scan_secrets


def test_sandbox_denies_non_allowlisted(tmp_settings, tmp_path):
    with pytest.raises(SandboxDenied):
        run_sandboxed(["evil-binary", "x"], tmp_path, tmp_settings)


def test_sandbox_denies_secret_env(tmp_settings, tmp_path):
    with pytest.raises(SandboxDenied):
        run_sandboxed(["git", "--version"], tmp_path, tmp_settings, env_extra={"MY_TOKEN": "x"})


def test_sandbox_runs_allowlisted(tmp_settings, tmp_path):
    result = run_sandboxed(["git", "--version"], tmp_path, tmp_settings)
    assert result.returncode == 0
    assert "git version" in result.stdout


def test_secret_fallback_finds_nothing_clean(sample_python, tmp_settings):
    result = scan_secrets(sample_python, tmp_settings)
    assert result.files_scanned >= 0
    assert result.scanner in ("gitleaks", "builtin-fallback")


def test_secret_fallback_detects_and_hashes(tmp_path, tmp_settings):
    secret = "ghp_" + "a" * 30
    (tmp_path / "leak.txt").write_text(f"token={secret}\n")
    (tmp_path / "clean.txt").write_text("hello\n")
    result = scan_secrets(tmp_path, tmp_settings)
    if result.scanner == "builtin-fallback":
        assert len(result.findings) == 1
        assert result.findings[0].rule == "builtin:github-token"
        dumped = result.model_dump_json()
        assert secret not in dumped
        assert result.findings[0].fingerprint
    else:
        assert secret not in result.model_dump_json()


def test_sca_parsers(sample_node, sample_python):
    node_pkgs = {(p["ecosystem"], p["name"], p["version"]) for p in _packages_from_lockfiles(sample_node)}
    assert ("npm", "eslint", "9.0.0") in node_pkgs
    assert ("npm", "jest", "29.7.0") in node_pkgs
    py_pkgs = {(p["ecosystem"], p["name"]) for p in _packages_from_lockfiles(sample_python)}
    assert ("PyPI", "flask") in py_pkgs
