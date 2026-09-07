"""Repository discovery on fixture repos."""
from ci_agent.discovery.repo import LocalRepo, discover


def test_sample_python(sample_python, tmp_settings):
    repo = LocalRepo(path=sample_python, commit_sha="fixture", default_branch="", revision_requested="")
    ctx = discover(repo, "https://github.com/acme/sample-python")
    assert [l.name for l in ctx.languages] == ["python"]
    assert ctx.package_managers == ["pip"]
    assert "pyproject.toml" in ctx.dependency_files
    assert "requirements.txt" in ctx.dependency_files
    assert ctx.test_setups and ctx.test_setups[0].framework == "pytest"
    assert ctx.has_dockerfile
    assert [c.path for c in ctx.existing_ci] == [".github/workflows/old.yml"]
    assert ctx.existing_ci[0].triggers == ["push"]
    assert ctx.licenses == ["MIT"]
    assert ctx.context_hash
    assert ctx.evidence


def test_sample_node(sample_node, tmp_settings):
    repo = LocalRepo(path=sample_node, commit_sha="fixture", default_branch="", revision_requested="")
    ctx = discover(repo, "https://github.com/acme/sample-node")
    assert [l.name for l in ctx.languages] == ["node"]
    assert ctx.package_managers == ["npm"]
    assert "package-lock.json" in ctx.lockfiles
    assert ctx.test_setups and ctx.test_setups[0].framework == "jest"
    assert not ctx.has_dockerfile


def test_local_path_blocked_by_default(sample_python, tmp_path):
    from ci_agent.common import db as db_module
    from ci_agent.config import Settings, reset_settings
    from ci_agent.discovery.repo import RepoAdapter

    db_module.reset_engine()
    reset_settings()
    try:
        settings = Settings(ALLOW_LOCAL_REPOS=False)
        try:
            RepoAdapter(settings).prepare(str(sample_python), "", tmp_path / "repo")
        except ValueError as exc:
            assert "ALLOW_LOCAL_REPOS" in str(exc)
            return
        raise AssertionError("expected local paths to be rejected")
    finally:
        db_module.reset_engine()
        reset_settings()
