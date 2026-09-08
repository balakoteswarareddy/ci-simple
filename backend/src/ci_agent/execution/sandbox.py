"""Sandboxed command runner (PDF §7 execution isolation, Phase 6).

Allow-listed argv only, no shell, scrubbed environment, timeouts, POSIX
resource limits, and optional docker isolation. Used for dry-runs and any
future command execution — the LLM never gets a raw shell.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..observability.logging import get_logger
from ..security.redact import redact

LOG = get_logger("ci_agent.execution")

OUTPUT_CAP = 100_000


class SandboxDenied(ValueError):
    pass


@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    mode: str = "local"


def _scrubbed_env(extra: dict[str, str] | None) -> dict[str, str]:
    keep_prefixes = ("PATH", "HOME", "LANG", "LC_", "CI", "GITHUB_", "GIT_")
    env = {
        k: v for k, v in os.environ.items()
        if k.startswith(keep_prefixes) and "TOKEN" not in k and "SECRET" not in k and "KEY" not in k
    }
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    for key, value in (extra or {}).items():
        upper = key.upper()
        if "TOKEN" in upper or "SECRET" in upper or upper.endswith("KEY"):
            raise SandboxDenied(f"refusing to pass secret-like env var '{key}' into sandbox")
        env[key] = value
    return env


def _limit_resources(timeout: int) -> None:  # pragma: no cover - platform specific
    try:
        import resource

        cpu = timeout + 60
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        mem = 2 * 1024 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        filesize = 512 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_FSIZE, (filesize, filesize))
    except (ImportError, OSError, ValueError):
        pass


def run_sandboxed(
    argv: list[str],
    cwd: Path,
    settings: Settings,
    env_extra: dict[str, str] | None = None,
    timeout: int | None = None,
) -> SandboxResult:
    if not argv:
        raise SandboxDenied("empty command")
    binary = Path(argv[0]).name
    if binary not in settings.sandbox_allowed_commands_list:
        raise SandboxDenied(f"command '{binary}' is not in the sandbox allow-list")
    timeout = timeout or settings.sandbox_timeout_seconds
    env = _scrubbed_env(env_extra)
    if settings.sandbox_mode == "docker":
        return _run_docker(argv, cwd, settings, env, timeout)
    return _run_local(argv, cwd, env, timeout)


def _run_local(argv: list[str], cwd: Path, env: dict[str, str], timeout: int) -> SandboxResult:
    import functools

    preexec = functools.partial(_limit_resources, timeout) if os.name == "posix" else None
    try:
        proc = subprocess.run(
            argv, cwd=str(cwd), env=env, capture_output=True, text=True,
            timeout=timeout, preexec_fn=preexec,
        )
        return SandboxResult(
            returncode=proc.returncode,
            stdout=redact(proc.stdout[-OUTPUT_CAP:]),
            stderr=redact(proc.stderr[-OUTPUT_CAP:]),
            mode="local",
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return SandboxResult(returncode=124, stdout=redact(out[-OUTPUT_CAP:]),
                             stderr=redact(err[-OUTPUT_CAP:]), timed_out=True, mode="local")


def _run_docker(argv: list[str], cwd: Path, settings: Settings, env: dict[str, str], timeout: int) -> SandboxResult:
    docker = shutil.which("docker")
    if not docker:
        raise SandboxDenied("SANDBOX_MODE=docker but no docker binary is available")
    docker_argv = [
        docker, "run", "--rm",
        "--network", "bridge" if settings.sandbox_allow_network else "none",
        "--memory", "2g", "--cpus", "2",
        "-v", f"{cwd}:/work:rw", "-w", "/work",
        settings.sandbox_docker_image, *argv,
    ]
    LOG.info("docker sandbox image=%s cmd=%s", settings.sandbox_docker_image, argv[0])
    try:
        proc = subprocess.run(docker_argv, capture_output=True, text=True, timeout=timeout)
        return SandboxResult(
            returncode=proc.returncode,
            stdout=redact(proc.stdout[-OUTPUT_CAP:]),
            stderr=redact(proc.stderr[-OUTPUT_CAP:]),
            mode="docker",
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(returncode=124, stdout="", stderr="docker run timed out", timed_out=True, mode="docker")
