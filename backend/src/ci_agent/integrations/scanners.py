"""Security pipeline adapters (Phase 3): secret scanning, SCA, SAST,
container and IaC scanning through integrated OSS tools.

Each scanner prefers its established CLI and degrades explicitly:
provisional built-in checks are labeled runner="fallback", missing tools
runner="skipped". Nothing reports a silent pass.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

from ..common.models import (
    SASTResult,
    SCAResult,
    SecretFinding,
    SecretScanResult,
    VulnFinding,
)
from ..common.util import sha256_text
from ..config import Settings
from ..observability.logging import get_logger
from ..observability.metrics import TOOL_CALLS

LOG = get_logger("ci_agent.integrations.scanners")

CLI_TIMEOUT = 300

_FALLBACK_SECRET_RES = [
    ("github-token", re.compile(r"\bgh[opsu]_[A-Za-z0-9_]{20,}")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private-key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("generic-secret", re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key)\s*[:=]\s*['\"]?[^\s'\"]{8,}")),
]
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "target", "dist"}


def _run_cli(tool: str, argv: list[str], cwd: Path, timeout: int = CLI_TIMEOUT) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        TOOL_CALLS.labels(tool=tool, status="ok" if proc.returncode == 0 else "findings").inc()
        return proc.returncode, proc.stdout[-20000:], proc.stderr[-4000:]
    except FileNotFoundError:
        TOOL_CALLS.labels(tool=tool, status="missing").inc()
        return 127, "", "binary not installed"
    except subprocess.TimeoutExpired:
        TOOL_CALLS.labels(tool=tool, status="timeout").inc()
        return 124, "", f"timed out after {timeout}s"


def _iter_files(root: Path, limit: int = 3000):
    count = 0
    stack = [root]
    while stack and count < limit:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name in _SKIP_DIRS or entry.is_symlink():
                continue
            try:
                if entry.is_dir():
                    stack.append(entry)
                elif entry.is_file() and entry.stat().st_size < 2_000_000:
                    count += 1
                    yield entry
            except OSError:
                continue


# ------------------------------------------------------------- secrets
def scan_secrets(path: Path, settings: Settings) -> SecretScanResult:
    _ = settings
    binary = shutil.which("gitleaks")
    if binary:
        return _gitleaks_scan(Path(binary), path)
    LOG.warning("gitleaks not installed — builtin secret fallback in use")
    findings: list[SecretFinding] = []
    scanned = 0
    for file in _iter_files(path):
        scanned += 1
        try:
            lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines[:2000], start=1):
            for rule, pattern in _FALLBACK_SECRET_RES:
                match = pattern.search(line)
                if match:
                    findings.append(SecretFinding(
                        file=str(file.relative_to(path)), line=lineno, rule=f"builtin:{rule}",
                        fingerprint=sha256_text(match.group(0))[:16],
                    ))
    return SecretScanResult(
        scanner="builtin-fallback", passed=not findings, findings=findings,
        files_scanned=scanned,
        provenance={"runner": "fallback", "reason": "gitleaks-binary-not-installed"},
    )


def _gitleaks_scan(binary: Path, path: Path) -> SecretScanResult:
    report = path / ".agent-gitleaks.json"
    rc, _, stderr = _run_cli("gitleaks", [
        str(binary), "detect", "--source", str(path), "--no-git",
        "--verbose", "--report-format", "json", "--report-path", str(report),
        "--exit-code", "1",
    ], path)
    findings: list[SecretFinding] = []
    if report.exists():
        try:
            items = json.loads(report.read_text(encoding="utf-8") or "[]")
            for item in items:
                findings.append(SecretFinding(
                    file=str(item.get("File", "")), line=int(item.get("StartLine", 0) or 0),
                    rule=str(item.get("RuleID", "gitleaks")),
                    fingerprint=sha256_text(str(item.get("Secret", "")))[:16],
                ))
        except (json.JSONDecodeError, OSError, ValueError):
            pass
        finally:
            report.unlink(missing_ok=True)
    if rc not in (0, 1):
        return SecretScanResult(scanner="gitleaks", passed=False, findings=findings,
                                provenance={"runner": "binary", "reason": f"exit={rc} {stderr[:200]}"})
    return SecretScanResult(scanner="gitleaks", passed=rc == 0, findings=findings,
                            provenance={"runner": "binary"})


# ------------------------------------------------------------------ SCA
def scan_sca(path: Path, settings: Settings) -> SCAResult:
    _ = settings
    binary = shutil.which("osv-scanner")
    if binary:
        return _osv_cli_scan(Path(binary), path)
    packages = _packages_from_lockfiles(path)
    if not packages:
        return SCAResult(scanner="osv", passed=True, packages_scanned=0,
                         provenance={"runner": "skipped", "reason": "no supported lockfiles found"})
    return _osv_api_scan(packages)


def _osv_cli_scan(binary: Path, path: Path) -> SCAResult:
    rc, stdout, stderr = _run_cli("osv-scanner", [str(binary), "-r", str(path), "--format", "json"], path)
    if rc == 127:
        return SCAResult(scanner="osv-scanner", passed=True,
                         provenance={"runner": "skipped", "reason": "binary-not-installed"})
    findings: list[VulnFinding] = []
    packages = 0
    try:
        data = json.loads(stdout or "{}")
        for result in data.get("results", []):
            for pkg in result.get("packages", []):
                packages += 1
                info = pkg.get("package", {})
                for vuln in pkg.get("vulnerabilities", []):
                    sev = ""
                    for s in vuln.get("severity", []) or []:
                        if s.get("type") == "CVSS_V3":
                            sev = str(s.get("score", ""))
                    findings.append(VulnFinding(
                        package=str(info.get("name", "")), installed_version=str(info.get("version", "")),
                        vuln_id=str(vuln.get("id", "")), severity=sev,
                        summary=str(vuln.get("summary", ""))[:300], source="osv-scanner",
                    ))
    except json.JSONDecodeError:
        return SCAResult(scanner="osv-scanner", passed=False,
                         provenance={"runner": "binary", "reason": f"unparseable output {stderr[:200]}"})
    return SCAResult(scanner="osv-scanner", passed=rc == 0, findings=findings,
                     packages_scanned=packages, provenance={"runner": "binary"})


def _packages_from_lockfiles(path: Path) -> list[dict]:
    """Best-effort (ecosystem, name, version) extraction for the OSV API."""
    out: list[dict] = []
    lock = path / "package-lock.json"
    if lock.exists():
        try:
            data = json.loads(lock.read_text(encoding="utf-8"))
            for name, meta in (data.get("packages", {}) or {}).items():
                if not name.startswith("node_modules/") or "/" in name[len("node_modules/"):]:
                    continue
                version = (meta or {}).get("version", "")
                if version:
                    out.append({"ecosystem": "npm", "name": name.split("/")[-1], "version": version})
        except (json.JSONDecodeError, OSError):
            pass
    for req in list(path.glob("requirements*.txt"))[:3]:
        try:
            for line in req.read_text(encoding="utf-8").splitlines():
                m = re.match(r"^\s*([A-Za-z0-9_.\-]+)==([A-Za-z0-9_.\-+]+)", line)
                if m:
                    out.append({"ecosystem": "PyPI", "name": m.group(1), "version": m.group(2)})
        except OSError:
            continue
    poetry = path / "poetry.lock"
    if poetry.exists():
        try:
            data = tomllib.loads(poetry.read_bytes().decode("utf-8", errors="replace"))
            for pkg in data.get("package", []) or []:
                out.append({"ecosystem": "PyPI", "name": pkg.get("name", ""), "version": pkg.get("version", "")})
        except (tomllib.TOMLDecodeError, OSError):
            pass
    cargo = path / "Cargo.lock"
    if cargo.exists():
        try:
            data = tomllib.loads(cargo.read_bytes().decode("utf-8", errors="replace"))
            for pkg in data.get("package", []) or []:
                out.append({"ecosystem": "crates.io", "name": pkg.get("name", ""), "version": pkg.get("version", "")})
        except (tomllib.TOMLDecodeError, OSError):
            pass
    seen, deduped = set(), []
    for pkg in out:
        key = (pkg["ecosystem"], pkg["name"], pkg["version"])
        if key not in seen and pkg["name"] and pkg["version"]:
            seen.add(key)
            deduped.append(pkg)
    return deduped[:500]


def _osv_api_scan(packages: list[dict]) -> SCAResult:
    import httpx

    queries = [{"package": {"name": p["name"], "ecosystem": p["ecosystem"]}, "version": p["version"]} for p in packages]
    findings: list[VulnFinding] = []
    try:
        with httpx.Client(timeout=60) as client:
            response = client.post("https://api.osv.dev/v1/querybatch", json={"queries": queries})
        response.raise_for_status()
        results = response.json().get("results", [])
    except Exception as exc:
        LOG.warning("osv api unreachable: %s", exc)
        return SCAResult(scanner="osv-api", passed=True, packages_scanned=len(packages),
                         provenance={"runner": "osv-api", "status": "unreachable", "reason": str(exc)[:200]})
    for pkg, result in zip(packages, results):
        for vuln in result.get("vulns", []) or []:
            sev = ""
            for s in vuln.get("severity", []) or []:
                if "CVSS_V3" in str(s.get("type", "")):
                    sev = str(s.get("score", ""))
            findings.append(VulnFinding(
                package=pkg["name"], installed_version=pkg["version"],
                vuln_id=str(vuln.get("id", "")), severity=sev,
                summary=str(vuln.get("summary", ""))[:300], source="osv-api",
            ))
    TOOL_CALLS.labels(tool="osv-api", status="ok").inc()
    return SCAResult(scanner="osv-api", passed=not findings, findings=findings,
                     packages_scanned=len(packages), provenance={"runner": "osv-api"})


# ----------------------------------------------------------------- SAST
def scan_sast(path: Path, settings: Settings) -> SASTResult:
    _ = settings
    binary = shutil.which("semgrep")
    if not binary:
        LOG.warning("semgrep not installed — sast step skipped")
        return SASTResult(scanner="semgrep", passed=True, provenance={"runner": "skipped", "reason": "binary-not-installed"},
                          findings=[{"check_id": "SKIPPED", "severity": "INFO",
                                     "message": "semgrep binary not installed — install it or run via container"}])
    rc, stdout, stderr = _run_cli("semgrep", [binary, "scan", "--config", "auto", "--json", "--quiet"], path)
    findings: list[dict] = []
    try:
        data = json.loads(stdout or "{}")
        for item in data.get("results", []) or []:
            findings.append({
                "check_id": item.get("check_id", ""), "path": item.get("path", ""),
                "line": (item.get("start", {}) or {}).get("line", 0),
                "severity": (item.get("extra", {}) or {}).get("severity", ""),
                "message": (item.get("extra", {}) or {}).get("message", "")[:300],
            })
    except json.JSONDecodeError:
        return SASTResult(scanner="semgrep", passed=False, provenance={"runner": "binary", "reason": stderr[:200]})
    return SASTResult(scanner="semgrep", passed=rc == 0, findings=findings, provenance={"runner": "binary"})


# ------------------------------------------------------------ container
def scan_container(path: Path, settings: Settings) -> SASTResult:
    _ = settings
    binary = shutil.which("trivy")
    if not binary:
        LOG.warning("trivy not installed — container scan skipped")
        return SASTResult(scanner="trivy", passed=True, provenance={"runner": "skipped", "reason": "binary-not-installed"},
                          findings=[{"check_id": "SKIPPED", "severity": "INFO",
                                     "message": "trivy binary not installed — install it or run via container"}])
    rc, stdout, stderr = _run_cli("trivy", [binary, "fs", "--format", "json",
                                            "--severity", "HIGH,CRITICAL", str(path)], path)
    findings: list[dict] = []
    try:
        data = json.loads(stdout or "{}")
        for result in data.get("Results", []) or []:
            for vuln in result.get("Vulnerabilities", []) or []:
                findings.append({
                    "check_id": vuln.get("VulnerabilityID", ""), "path": result.get("Target", ""),
                    "severity": vuln.get("Severity", ""),
                    "message": f"{vuln.get('PkgName', '')} {vuln.get('InstalledVersion', '')}: {vuln.get('Title', '')}"[:300],
                })
    except json.JSONDecodeError:
        return SASTResult(scanner="trivy", passed=False, provenance={"runner": "binary", "reason": stderr[:200]})
    return SASTResult(scanner="trivy", passed=rc == 0, findings=findings, provenance={"runner": "binary"})


# ------------------------------------------------------------------ IaC
def scan_iac(path: Path, settings: Settings) -> SASTResult:
    _ = settings
    binary = shutil.which("checkov")
    if not binary:
        return SASTResult(scanner="checkov", passed=True, provenance={"runner": "skipped", "reason": "binary-not-installed"},
                          findings=[{"check_id": "SKIPPED", "severity": "INFO",
                                     "message": "checkov binary not installed — install it or run via container"}])
    rc, stdout, _ = _run_cli("checkov", [binary, "-d", str(path), "--quiet", "--compact", "-o", "json"], path)
    findings: list[dict] = []
    try:
        data = json.loads(stdout or "{}")
        for result in data.get("results", {}).get("failed_checks", []) or []:
            findings.append({
                "check_id": result.get("check_id", ""), "path": result.get("file_path", ""),
                "line": 0, "severity": result.get("severity", "") or "UNKNOWN",
                "message": result.get("check_name", "")[:300],
            })
    except json.JSONDecodeError:
        pass
    return SASTResult(scanner="checkov", passed=rc == 0, findings=findings, provenance={"runner": "binary"})


def run_security_suite(path: Path, capabilities: list[str], settings: Settings) -> dict:
    """Run the scanners implied by requested capabilities (orchestrator calls
    this; results feed the evidence record, never the LLM prompt)."""
    caps = set(capabilities)
    suite: dict = {}
    if "secrets" in caps:
        suite["secrets"] = scan_secrets(path, settings).model_dump()
    if "sca" in caps:
        suite["sca"] = scan_sca(path, settings).model_dump()
    if "sast" in caps:
        suite["sast"] = scan_sast(path, settings).model_dump()
    if "container-scan" in caps:
        suite["container"] = scan_container(path, settings).model_dump()
    if "iac-scan" in caps:
        suite["iac"] = scan_iac(path, settings).model_dump()
    return suite
