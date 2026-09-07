"""Repository intelligence (PDF §4): deterministic discovery that creates
evidence-backed context, not guesses. Every fact carries its source file."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

from ..common.models import (
    EvidenceItem,
    ExistingCI,
    RepoLanguage,
    RepositoryContext,
    TestSetup,
)
from ..common.util import sha256_text, utcnow
from ..config import Settings
from ..observability.logging import get_logger
from ..security.redact import redact

LOG = get_logger("ci_agent.discovery")

MAX_FILES = 8000
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".nox",
    "target", "dist", "build", "out", ".idea", ".vscode", "coverage",
    ".next", ".nuxt", ".cache", "vendor", "Pods",
}


@dataclass
class LocalRepo:
    path: Path
    commit_sha: str
    default_branch: str
    revision_requested: str


def _run(cmd: list[str], cwd: Path | None, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout
    )


class RepoAdapter:
    """Clones/resolves repositories safely (PDF §5 steps 2-3)."""

    def __init__(self, settings: Settings):
        self.settings = settings

    # -- public ------------------------------------------------------
    def prepare(self, repo_url: str, revision: str, dest_dir: Path) -> LocalRepo:
        repo_url = repo_url.strip()
        local = self._as_local_path(repo_url)
        if local is not None:
            return self._prepare_local(local, revision, repo_url)
        return self._prepare_remote(repo_url, revision, dest_dir)

    # -- local paths (dev/tests only) --------------------------------
    def _as_local_path(self, repo_url: str) -> Path | None:
        candidate = repo_url
        if candidate.startswith("file://"):
            candidate = candidate[len("file://"):]
        path = Path(candidate).expanduser()
        if path.exists() and path.is_dir():
            return path
        return None

    def _prepare_local(self, path: Path, revision: str, repo_url: str) -> LocalRepo:
        if not self.settings.allow_local_repos:
            raise ValueError("local repository paths are disabled (ALLOW_LOCAL_REPOS=false)")
        sha = ""
        proc = _run(["git", "-C", str(path), "rev-parse", "HEAD"], None, 30)
        if proc.returncode == 0:
            sha = proc.stdout.strip()
            if revision:
                co = _run(["git", "-C", str(path), "rev-parse", revision], None, 30)
                if co.returncode == 0:
                    sha = co.stdout.strip()
        else:
            # Not a git checkout (e.g. test fixture): fingerprint the tree.
            listing = sorted(str(p.relative_to(path)) for p in path.rglob("*") if p.is_file())
            sha = "local-" + sha256_text("\n".join(listing))[:16]
        LOG.info("prepared local repo path=%s sha=%s", redact(repo_url), sha[:12])
        return LocalRepo(path=path.resolve(), commit_sha=sha, default_branch="", revision_requested=revision)

    # -- remote clone -------------------------------------------------
    def _prepare_remote(self, repo_url: str, revision: str, dest_dir: Path) -> LocalRepo:
        parsed = urlparse(repo_url)
        if parsed.scheme not in ("https",):
            raise ValueError(f"only https git URLs are supported, got scheme '{parsed.scheme}'")
        if parsed.hostname.lower() not in self.settings.allowed_git_hosts_list:
            raise ValueError(f"git host '{parsed.hostname}' is not allow-listed")
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        dest_dir.parent.mkdir(parents=True, exist_ok=True)

        authed = self._authed_url(repo_url, parsed.hostname.lower())
        timeout = self.settings.clone_timeout_seconds
        depth = str(self.settings.clone_depth)
        LOG.info("cloning repo host=%s depth=%s", parsed.hostname, depth)
        proc = _run(
            ["git", "clone", "--depth", depth, "--no-checkout", authed, str(dest_dir)],
            None, timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"git clone failed: {redact(proc.stderr[-500:])}")

        target = revision.strip() or self._remote_default_branch(dest_dir)
        fetch = _run(["git", "-C", str(dest_dir), "fetch", "--depth", depth, "origin", target], None, timeout)
        if fetch.returncode != 0:
            # Maybe a full SHA already present, or a tag — try direct checkout.
            LOG.warning("fetch of revision failed, trying direct checkout revision=%s", redact(target))
        checkout = _run(["git", "-C", str(dest_dir), "checkout", "--force", target], None, timeout)
        if checkout.returncode != 0:
            raise RuntimeError(f"git checkout '{redact(target)}' failed: {redact(checkout.stderr[-500:])}")
        sha = _run(["git", "-C", str(dest_dir), "rev-parse", "HEAD"], None, 30).stdout.strip()
        branch = ""
        br = _run(["git", "-C", str(dest_dir), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], None, 30)
        if br.returncode == 0:
            branch = br.stdout.strip().split("/", 1)[-1]
        LOG.info("checked out sha=%s default_branch=%s", sha[:12], branch)
        return LocalRepo(path=dest_dir.resolve(), commit_sha=sha, default_branch=branch, revision_requested=revision)

    def _remote_default_branch(self, repo_dir: Path) -> str:
        proc = _run(["git", "-C", str(repo_dir), "symbolic-ref", "refs/remotes/origin/HEAD"], None, 30)
        if proc.returncode == 0:
            return proc.stdout.strip().split("/")[-1]
        return "HEAD"

    def _authed_url(self, repo_url: str, host: str) -> str:
        token = self.settings.github_token
        if not token or host != "github.com":
            return repo_url
        return repo_url.replace("https://", f"https://x-access-token:{token}@", 1)


# =====================================================================
# Discovery
# =====================================================================
def _walk(root: Path) -> list[Path]:
    out: list[Path] = []
    stack = [root]
    while stack and len(out) < MAX_FILES:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name in SKIP_DIRS:
                continue
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    stack.append(entry)
                elif entry.is_file():
                    out.append(entry)
            except OSError:
                continue
    return out


def _read_text(path: Path, limit: int = 20000) -> str:
    try:
        data = path.read_bytes()[:limit]
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _ev(source_type: str, source: str, detail: str = "", text: str = "") -> EvidenceItem:
    return EvidenceItem(
        source_type=source_type,
        source=source,
        detail=detail[:300],
        excerpt_hash=sha256_text(text[:500])[:16] if text else "",
        retrieved_at=utcnow(),
    )


def discover(repo: LocalRepo, repo_url: str, settings: Settings | None = None) -> RepositoryContext:
    """Inspect a prepared checkout and build the RepositoryContext (§11)."""
    root = repo.path
    files = _walk(root)
    by_name: dict[str, list[Path]] = {}
    for f in files:
        by_name.setdefault(f.name, []).append(f)

    def rel(p: Path) -> str:
        return str(p.relative_to(root))

    ctx = RepositoryContext(
        repo_url=repo_url,
        revision=repo.revision_requested,
        commit_sha=repo.commit_sha,
        default_branch=repo.default_branch,
        total_files=len(files),
    )

    _detect_python(root, by_name, rel, ctx)
    _detect_node(root, by_name, rel, ctx)
    _detect_go(root, by_name, rel, ctx)
    _detect_rust(root, by_name, rel, ctx)
    _detect_java(root, by_name, rel, ctx)
    _detect_ruby(root, by_name, rel, ctx)
    _detect_php(root, by_name, rel, ctx)
    _detect_csharp(root, by_name, rel, ctx)
    _detect_docker(root, by_name, rel, ctx)
    _detect_existing_ci(root, by_name, rel, ctx)
    _detect_licenses(root, by_name, rel, ctx)

    ctx.dependency_files = sorted(set(ctx.dependency_files))
    ctx.lockfiles = sorted(set(ctx.lockfiles))
    ctx.package_managers = sorted(set(ctx.package_managers))
    ctx.context_hash = ctx.compute_hash()
    LOG.info(
        "discovered repo languages=%s managers=%s tests=%s ci=%s files=%d",
        [l.name for l in ctx.languages], ctx.package_managers,
        [t.framework or t.command for t in ctx.test_setups],
        [c.path for c in ctx.existing_ci], ctx.total_files,
    )
    return ctx


# -- language detectors -----------------------------------------------
def _detect_python(root, by_name, rel, ctx) -> None:
    markers = [p for n in ("pyproject.toml", "setup.py", "setup.cfg", "Pipfile") for p in by_name.get(n, [])]
    reqs = [p for n, ps in by_name.items() if re.match(r"requirements.*\.txt", n) for p in ps]
    if not markers and not reqs:
        return
    constraint, manager, test_fw, test_cfg = "", "pip", "", []
    for p in by_name.get("pyproject.toml", [])[:1]:
        text = _read_text(p)
        try:
            data = tomllib.loads(text)
            constraint = str(data.get("project", {}).get("requires-python", ""))
            if "tool" in data and "poetry" in data["tool"]:
                manager = "poetry"
            if "tool" in data and "pdm" in data["tool"]:
                manager = "pdm"
            if "pytest" in text:
                test_fw, test_cfg = "pytest", [rel(p)]
        except tomllib.TOMLDecodeError:
            pass
        ctx.evidence.append(_ev("repo_file", rel(p), "python manifest", text))
    if by_name.get("poetry.lock"):
        manager = "poetry"
        ctx.lockfiles.append(rel(by_name["poetry.lock"][0]))
    if by_name.get("Pipfile.lock"):
        manager = "pipenv"
        ctx.lockfiles.append(rel(by_name["Pipfile.lock"][0]))
    if by_name.get("pdm.lock"):
        manager = "pdm"
        ctx.lockfiles.append(rel(by_name["pdm.lock"][0]))
    for p in reqs[:5]:
        ctx.evidence.append(_ev("repo_file", rel(p), "python requirements", _read_text(p, 500)))
    if not test_fw and ((root / "tests").is_dir() or by_name.get("pytest.ini") or by_name.get("tox.ini")):
        test_fw = "pytest"
    for name in ("pytest.ini", "tox.ini", "setup.cfg"):
        for p in by_name.get(name, [])[:1]:
            test_cfg.append(rel(p))
    lang = RepoLanguage(name="python", version_constraint=constraint, package_manager=manager)
    ctx.languages.append(lang)
    ctx.package_managers.append(manager)
    ctx.dependency_files += [rel(p) for p in markers[:4]] + [rel(p) for p in reqs[:4]]
    ctx.test_setups.append(TestSetup(framework=test_fw, command="pytest -q" if test_fw == "pytest" else "", config_files=sorted(set(test_cfg))))


def _detect_node(root, by_name, rel, ctx) -> None:
    pkg_files = by_name.get("package.json", [])
    if not pkg_files:
        return
    manager, constraint, test_fw, test_cmd = "npm", "", "", "npm test"
    for p in pkg_files[:1]:
        text = _read_text(p)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {}
        engines = data.get("engines", {}) or {}
        constraint = str(engines.get("node", ""))
        pm_field = str(data.get("packageManager", ""))
        if pm_field.startswith("yarn"):
            manager = "yarn"
        elif pm_field.startswith("pnpm"):
            manager = "pnpm"
        scripts = data.get("scripts", {}) or {}
        if not scripts.get("test"):
            test_cmd = ""
        deps = {**(data.get("dependencies", {}) or {}), **(data.get("devDependencies", {}) or {})}
        if "vitest" in deps:
            test_fw = "vitest"
        elif "jest" in deps:
            test_fw = "jest"
        elif "mocha" in deps:
            test_fw = "mocha"
        ctx.evidence.append(_ev("repo_file", rel(p), f"node manifest scripts={sorted(scripts)[:8]}", text))
    for lock, mgr in (("package-lock.json", "npm"), ("yarn.lock", "yarn"), ("pnpm-lock.yaml", "pnpm")):
        if by_name.get(lock):
            manager = mgr
            ctx.lockfiles.append(rel(by_name[lock][0]))
    ctx.languages.append(RepoLanguage(name="node", version_constraint=constraint, package_manager=manager))
    ctx.package_managers.append(manager)
    ctx.dependency_files += [rel(p) for p in pkg_files[:2]]
    if test_cmd or test_fw:
        ctx.test_setups.append(TestSetup(framework=test_fw, command=test_cmd, config_files=[rel(pkg_files[0])]))


def _detect_go(root, by_name, rel, ctx) -> None:
    mods = by_name.get("go.mod", [])
    if not mods:
        return
    constraint = ""
    text = _read_text(mods[0])
    m = re.search(r"^go\s+(\S+)", text, re.M)
    if m:
        constraint = m.group(1)
    has_tests = any(p.name.endswith("_test.go") for ps in by_name.values() for p in ps[:2000])
    ctx.languages.append(RepoLanguage(name="go", version_constraint=constraint, package_manager="go"))
    ctx.package_managers.append("go")
    ctx.dependency_files.append(rel(mods[0]))
    if by_name.get("go.sum"):
        ctx.lockfiles.append(rel(by_name["go.sum"][0]))
    ctx.evidence.append(_ev("repo_file", rel(mods[0]), "go module", text))
    if has_tests:
        ctx.test_setups.append(TestSetup(framework="go-test", command="go test ./...", config_files=[rel(mods[0])]))


def _detect_rust(root, by_name, rel, ctx) -> None:
    manifests = by_name.get("Cargo.toml", [])
    if not manifests:
        return
    edition = ""
    text = _read_text(manifests[0])
    try:
        edition = str(tomllib.loads(text).get("package", {}).get("edition", ""))
    except tomllib.TOMLDecodeError:
        pass
    ctx.languages.append(RepoLanguage(name="rust", version_constraint=edition, package_manager="cargo"))
    ctx.package_managers.append("cargo")
    ctx.dependency_files.append(rel(manifests[0]))
    if by_name.get("Cargo.lock"):
        ctx.lockfiles.append(rel(by_name["Cargo.lock"][0]))
    ctx.evidence.append(_ev("repo_file", rel(manifests[0]), "rust manifest", text))
    ctx.test_setups.append(TestSetup(framework="cargo-test", command="cargo test", config_files=[rel(manifests[0])]))


def _detect_java(root, by_name, rel, ctx) -> None:
    poms = by_name.get("pom.xml", [])
    gradles = by_name.get("build.gradle", []) + by_name.get("build.gradle.kts", [])
    if not poms and not gradles:
        return
    if poms:
        text = _read_text(poms[0])
        version = ""
        try:
            ns = {"m": "http://maven.apache.org/POM/4.0.0"}
            props = ET.fromstring(text).find("m:properties", ns)
            if props is not None:
                for key in ("maven.compiler.release", "maven.compiler.source", "java.version"):
                    node = props.find(f"m:{key}", ns)
                    if node is not None and node.text:
                        version = node.text.strip()
                        break
        except ET.ParseError:
            pass
        ctx.languages.append(RepoLanguage(name="java", version_constraint=version, package_manager="maven"))
        ctx.package_managers.append("maven")
        ctx.dependency_files.append(rel(poms[0]))
        ctx.evidence.append(_ev("repo_file", rel(poms[0]), "maven manifest", text))
        ctx.test_setups.append(TestSetup(framework="junit", command="mvn -q test", config_files=[rel(poms[0])]))
    if gradles:
        ctx.languages.append(RepoLanguage(name="java", version_constraint="", package_manager="gradle"))
        ctx.package_managers.append("gradle")
        ctx.dependency_files.append(rel(gradles[0]))
        ctx.evidence.append(_ev("repo_file", rel(gradles[0]), "gradle manifest", _read_text(gradles[0])))
        ctx.test_setups.append(TestSetup(framework="junit", command="./gradlew test", config_files=[rel(gradles[0])]))


def _detect_ruby(root, by_name, rel, ctx) -> None:
    gemfiles = by_name.get("Gemfile", [])
    if not gemfiles:
        return
    text = _read_text(gemfiles[0])
    m = re.search(r"ruby\s+['\"]([^'\"]+)['\"]", text)
    ctx.languages.append(RepoLanguage(name="ruby", version_constraint=m.group(1) if m else "", package_manager="bundler"))
    ctx.package_managers.append("bundler")
    ctx.dependency_files.append(rel(gemfiles[0]))
    if by_name.get("Gemfile.lock"):
        ctx.lockfiles.append(rel(by_name["Gemfile.lock"][0]))
    ctx.evidence.append(_ev("repo_file", rel(gemfiles[0]), "ruby manifest", text))
    if "rspec" in text or (root / "spec").is_dir():
        ctx.test_setups.append(TestSetup(framework="rspec", command="bundle exec rspec", config_files=[rel(gemfiles[0])]))


def _detect_php(root, by_name, rel, ctx) -> None:
    composers = by_name.get("composer.json", [])
    if not composers:
        return
    text = _read_text(composers[0])
    constraint = ""
    try:
        constraint = str((json.loads(text).get("require", {}) or {}).get("php", ""))
    except json.JSONDecodeError:
        pass
    ctx.languages.append(RepoLanguage(name="php", version_constraint=constraint, package_manager="composer"))
    ctx.package_managers.append("composer")
    ctx.dependency_files.append(rel(composers[0]))
    if by_name.get("composer.lock"):
        ctx.lockfiles.append(rel(by_name["composer.lock"][0]))
    ctx.evidence.append(_ev("repo_file", rel(composers[0]), "php manifest", text))
    if by_name.get("phpunit.xml") or by_name.get("phpunit.xml.dist"):
        cfg = rel((by_name.get("phpunit.xml") or by_name["phpunit.xml.dist"])[0])
        ctx.test_setups.append(TestSetup(framework="phpunit", command="vendor/bin/phpunit", config_files=[cfg]))


def _detect_csharp(root, by_name, rel, ctx) -> None:
    projects = [p for n, ps in by_name.items() if n.endswith(".csproj") for p in ps]
    solutions = [p for n, ps in by_name.items() if n.endswith(".sln") for p in ps]
    if not projects and not solutions:
        return
    version = ""
    if projects:
        text = _read_text(projects[0])
        m = re.search(r"<TargetFramework>([^<]+)</TargetFramework>", text)
        if m:
            version = m.group(1)
        ctx.evidence.append(_ev("repo_file", rel(projects[0]), "dotnet project", text))
    ctx.languages.append(RepoLanguage(name="csharp", version_constraint=version, package_manager="dotnet"))
    ctx.package_managers.append("dotnet")
    ctx.dependency_files += [rel(p) for p in (projects[:2] + solutions[:1])]
    ctx.test_setups.append(TestSetup(framework="dotnet-test", command="dotnet test", config_files=[rel(projects[0])] if projects else []))


def _detect_docker(root, by_name, rel, ctx) -> None:
    dockers = [p for n, ps in by_name.items() if n == "Dockerfile" or n.startswith("Dockerfile.") for p in ps]
    compose = [p for n, ps in by_name.items() if n in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml") for p in ps]
    if dockers:
        ctx.has_dockerfile = True
        ctx.dockerfiles = [rel(p) for p in dockers[:4]]
        ctx.evidence.append(_ev("repo_file", rel(dockers[0]), "docker build", _read_text(dockers[0])))
    for p in compose[:2]:
        ctx.evidence.append(_ev("repo_file", rel(p), "compose file", ""))


def _detect_existing_ci(root, by_name, rel, ctx) -> None:
    wf_dir = root / ".github" / "workflows"
    if wf_dir.is_dir():
        for p in sorted(wf_dir.glob("*.y*ml"))[:10]:
            triggers: list[str] = []
            try:
                data = yaml.safe_load(_read_text(p)) or {}
                on = data.get("on", data.get(True, ""))
                if isinstance(on, dict):
                    triggers = sorted(str(k) for k in on.keys())
                elif isinstance(on, list):
                    triggers = [str(k) for k in on]
                elif isinstance(on, str):
                    triggers = [on]
            except yaml.YAMLError:
                pass
            ctx.existing_ci.append(ExistingCI(platform="github", path=rel(p), triggers=triggers))
            ctx.evidence.append(_ev("repo_file", rel(p), f"existing github workflow triggers={triggers}", ""))
    for name, platform in ((".gitlab-ci.yml", "gitlab"), ("azure-pipelines.yml", "azure"), ("Jenkinsfile", "jenkins")):
        for p in by_name.get(name, [])[:2]:
            ctx.existing_ci.append(ExistingCI(platform=platform, path=rel(p)))
            ctx.evidence.append(_ev("repo_file", rel(p), f"existing {platform} ci", ""))


_LICENSE_MARKERS = [
    ("MIT License", "MIT"),
    ("Apache License", "Apache-2.0"),
    ("GNU GENERAL PUBLIC LICENSE", "GPL"),
    ("BSD 3-Clause", "BSD-3-Clause"),
    ("BSD 2-Clause", "BSD-2-Clause"),
    ("Mozilla Public License", "MPL-2.0"),
    ("ISC License", "ISC"),
]


def _detect_licenses(root, by_name, rel, ctx) -> None:
    for name, ps in by_name.items():
        if name.lower().startswith("license"):
            text = _read_text(ps[0])
            for marker, lic in _LICENSE_MARKERS:
                if marker in text:
                    if lic == "GPL":
                        lic = "GPL-3.0-only" if "Version 3" in text else "GPL-2.0-only"
                    ctx.licenses.append(lic)
                    ctx.evidence.append(_ev("repo_file", rel(ps[0]), f"license={lic}", text))
                    break
            break
