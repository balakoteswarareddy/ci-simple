"""Deterministic intent parsing (offline planner)."""
import pytest

from ci_agent.common.models import RepositoryContext
from ci_agent.llm.fallback import DeterministicClient
from ci_agent.planner.intent import parse_intent

CTX = RepositoryContext(repo_url="https://github.com/o/r", commit_sha="abc")


async def _parse(text, settings):
    llm = DeterministicClient(settings)
    intent, stats, _ = await parse_intent(text, CTX, settings, llm)
    return intent


async def test_pdf_example_intent(tmp_settings):
    intent = await _parse(
        "Create GitHub Actions CI for this Python API. Run tests, linting and security checks. Do not use Semgrep.",
        tmp_settings,
    )
    assert intent.platform == "github"
    assert set(["lint", "test", "sast", "sca", "secrets"]) <= set(intent.capabilities)
    assert intent.prohibited_tools == ["semgrep"]
    assert intent.planner == "deterministic-fallback"


async def test_platform_detection(tmp_settings):
    assert (await _parse("build a Jenkins pipeline with tests", tmp_settings)).platform == "jenkins"
    assert (await _parse("gitlab ci for this repo with lint", tmp_settings)).platform == "gitlab"
    assert (await _parse("azure pipelines with tests", tmp_settings)).platform == "azure"


async def test_default_capabilities(tmp_settings):
    intent = await _parse("hello, please help", tmp_settings)
    assert intent.capabilities == ["lint", "test"]


async def test_production_target(tmp_settings):
    intent = await _parse("deploy this to production with sign and sbom", tmp_settings)
    assert intent.deployment_target == "production"
    assert "deploy" in intent.capabilities
    assert "sign" in intent.capabilities
    assert "sbom" in intent.capabilities


async def test_unknown_capability_rejected(tmp_settings):
    from ci_agent.llm.base import LLMCallStats
    from ci_agent.common.models import UserIntent

    class Fake:
        name = "fake"

        async def parse_intent(self, request_text, repo_facts):
            return UserIntent(platform="github", capabilities=["teleport"]), LLMCallStats(model="fake")

    from ci_agent.planner.intent import IntentError

    with pytest.raises(IntentError):
        await parse_intent("x", CTX, tmp_settings, Fake())
