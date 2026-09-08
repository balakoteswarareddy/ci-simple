"""GitHub adapter (Phase 0 skeleton grown into Phase 5 PR automation).

Thin REST wrapper: resolve revisions, create branches, commit workflow files,
open PRs, read check runs. Mutations require GITHUB_TOKEN and (for protected
targets) a recorded approval — enforced by the orchestrator, not here.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..config import Settings
from ..observability.logging import get_logger
from ..observability.metrics import TOOL_CALLS
from ..security.redact import redact

LOG = get_logger("ci_agent.integrations.github")


class GitHubError(RuntimeError):
    pass


@dataclass
class RepoId:
    owner: str
    name: str


def parse_repo_url(url: str) -> RepoId:
    parsed = urlparse(url.strip())
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if parsed.hostname != "github.com" or len(parts) < 2:
        raise GitHubError(f"not a github repository URL: {redact(url)}")
    name = parts[1]
    if name.endswith(".git"):
        name = name[:-4]
    return RepoId(owner=parts[0], name=name)


class GitHubClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api = settings.github_api_url.rstrip("/")

    # -- low level -------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ci-agent/0.1"}
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        return headers

    def _record(self, operation: str, ok: bool) -> None:
        TOOL_CALLS.labels(tool=f"github:{operation}", status="ok" if ok else "error").inc()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8),
           retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)))
    async def _get(self, path: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.api}{path}", headers=self._headers())
        if response.status_code == 404:
            raise GitHubError(f"github resource not found: {path}")
        if response.status_code >= 400:
            raise GitHubError(f"github GET {path} failed ({response.status_code}): {response.text[:300]}")
        return response.json()

    async def _mutate(self, method: str, path: str, payload: dict) -> dict:
        if not self.settings.github_token:
            raise GitHubError("GITHUB_TOKEN is not configured — cannot mutate github")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, f"{self.api}{path}", headers=self._headers(), json=payload)
        if response.status_code >= 400:
            raise GitHubError(f"github {method} {path} failed ({response.status_code}): {response.text[:400]}")
        return response.json()

    # -- reads --------------------------------------------------------------
    async def get_repo(self, repo: RepoId) -> dict:
        try:
            data = await self._get(f"/repos/{repo.owner}/{repo.name}")
            self._record("get_repo", True)
            return {"default_branch": data.get("default_branch", "main"),
                    "is_fork": bool(data.get("fork", False)),
                    "private": bool(data.get("private", False))}
        except Exception:
            self._record("get_repo", False)
            raise

    async def resolve_branch(self, repo: RepoId, branch: str) -> str:
        data = await self._get(f"/repos/{repo.owner}/{repo.name}/branches/{branch}")
        return str(data["commit"]["sha"])

    async def get_file(self, repo: RepoId, path: str, ref: str) -> dict | None:
        try:
            data = await self._get(f"/repos/{repo.owner}/{repo.name}/contents/{path}?ref={ref}")
        except GitHubError as exc:
            if "not found" in str(exc):
                return None
            raise
        content = ""
        if data.get("encoding") == "base64" and data.get("content"):
            content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return {"sha": data.get("sha", ""), "content": content}

    async def list_check_runs(self, repo: RepoId, ref: str) -> list[dict]:
        try:
            data = await self._get(f"/repos/{repo.owner}/{repo.name}/commits/{ref}/check-runs")
            self._record("list_checks", True)
        except Exception:
            self._record("list_checks", False)
            raise
        return [
            {"name": r.get("name", ""), "status": r.get("status", ""),
             "conclusion": r.get("conclusion", ""), "url": r.get("html_url", "")}
            for r in data.get("check_runs", [])
        ]

    # -- mutations (Phase 5) ---------------------------------------------------
    async def create_branch(self, repo: RepoId, new_branch: str, sha: str) -> None:
        try:
            await self._mutate("POST", f"/repos/{repo.owner}/{repo.name}/git/refs",
                               {"ref": f"refs/heads/{new_branch}", "sha": sha})
            self._record("create_branch", True)
        except Exception:
            self._record("create_branch", False)
            raise

    async def put_file(self, repo: RepoId, path: str, content: str, message: str,
                       branch: str, sha: str | None = None) -> str:
        payload: dict = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        try:
            data = await self._mutate("PUT", f"/repos/{repo.owner}/{repo.name}/contents/{path}", payload)
            self._record("put_file", True)
            return str(data.get("commit", {}).get("sha", ""))
        except Exception:
            self._record("put_file", False)
            raise

    async def open_pr(self, repo: RepoId, title: str, head: str, base: str, body: str) -> dict:
        try:
            data = await self._mutate("POST", f"/repos/{repo.owner}/{repo.name}/pulls",
                                      {"title": title[:200], "head": head, "base": base, "body": body[:60000]})
            self._record("open_pr", True)
            return {"number": data.get("number"), "url": data.get("html_url", "")}
        except Exception:
            self._record("open_pr", False)
            raise


def merge_recommendation(checks: list[dict], policy_decision: str, validation_ok: bool) -> dict:
    """Reviewer-facing merge guidance (Phase 5). Recommendation only — the
    human (or branch protection) makes the call."""
    failures = [c for c in checks if c.get("conclusion") in ("failure", "timed_out", "cancelled")]
    pending = [c for c in checks if c.get("status") != "completed"]
    reasons: list[str] = []
    if policy_decision == "DENY":
        reasons.append("policy decision is DENY")
    if not validation_ok:
        reasons.append("workflow validation failed")
    if failures:
        reasons.append(f"{len(failures)} failing check(s): {', '.join(c['name'] for c in failures[:5])}")
    if pending:
        reasons.append(f"{len(pending)} check(s) still pending")
    if reasons:
        return {"recommendation": "do-not-merge", "reasons": reasons}
    if policy_decision == "APPROVAL_REQUIRED":
        return {"recommendation": "merge-after-approval", "reasons": ["policy requires a recorded approval"]}
    return {"recommendation": "ready-to-merge", "reasons": ["checks green, policy allows, validation passed"]}
