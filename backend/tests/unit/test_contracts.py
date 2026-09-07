"""Contract models, redaction, canonical commands."""
from ci_agent.common.models import (
    CandidatePlan,
    PipelineIR,
    PlannedTool,
    RepositoryContext,
)
from ci_agent.pipeline.commands import TOOL_COMMANDS, command_for
from ci_agent.security.redact import MASK, redact, redact_obj


def test_context_hash_stable():
    a = RepositoryContext(repo_url="https://x/y", commit_sha="abc")
    b = RepositoryContext(repo_url="https://x/y", commit_sha="abc")
    assert a.compute_hash() == b.compute_hash()
    b.commit_sha = "def"
    assert a.compute_hash() != b.compute_hash()


def test_plan_hash_changes_with_tools():
    p1 = CandidatePlan(tools=[PlannedTool(name="ruff", version="1")])
    p2 = CandidatePlan(tools=[PlannedTool(name="ruff", version="2")])
    assert p1.compute_hash() != p2.compute_hash()


def test_ir_hash_stable():
    ir = PipelineIR(platform="github", name="ci")
    assert ir.compute_hash() == PipelineIR(platform="github", name="ci").compute_hash()


def test_redact_github_token():
    assert "ghp_" + "x" * 30 not in redact("token=ghp_" + "x" * 30)
    assert MASK in redact("token=ghp_" + "x" * 30)


def test_redact_key_value_and_url():
    assert MASK in redact("password: s3cr3t-value")
    assert MASK in redact("https://user:s3cr3t@github.com/o/r")
    assert "github.com/o/r" in redact("https://user:s3cr3t@github.com/o/r")


def test_redact_obj_nested():
    payload = {"a": {"github_token": "ghp_" + "z" * 30}, "b": ["ok", "AKIAIOSFODNN7EXAMPLE"]}
    out = redact_obj(payload)
    assert out["a"]["github_token"] == MASK
    assert "AKIAIOSFODNN7EXAMPLE" not in str(out)


def test_redact_private_key():
    key = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOP...\n-----END RSA PRIVATE KEY-----"
    assert MASK in redact(key)


def test_canonical_commands_cover_approved_tools():
    import json
    from tests.conftest import OPA_STORE

    approved = json.loads((OPA_STORE / "data.json").read_text())["approved"]["tools"]
    missing = [t for t in approved if t not in TOOL_COMMANDS]
    assert missing == [], f"approved tools without canonical command: {missing}"


def test_command_for_unknown_raises():
    try:
        command_for("evil-backdoor")
    except KeyError:
        return
    raise AssertionError("expected KeyError for unknown tool")
