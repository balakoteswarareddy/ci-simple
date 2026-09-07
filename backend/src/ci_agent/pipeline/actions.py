"""Pinned GitHub Action versions used by the deterministic renderer.

Tags (not SHAs) are emitted for readability and reliability; harden any
generated workflow to immutable SHAs with backend/scripts/pin_actions.py
before production use. Every entry here must match a prefix in the approved
action catalog or policy will deny the plan.
"""
from __future__ import annotations

KNOWN_ACTION_VERSIONS: dict[str, str] = {
    "actions/checkout": "v4",
    "actions/setup-python": "v5",
    "actions/setup-node": "v4",
    "actions/setup-go": "v5",
    "actions/setup-java": "v4",
    "actions/setup-dotnet": "v4",
    "actions/cache": "v4",
    "actions/upload-artifact": "v4",
    "actions/download-artifact": "v4",
    "github/codeql-action/upload-sarif": "v3",
    "docker/setup-buildx-action": "v3",
    "docker/build-push-action": "v6",
    "docker/login-action": "v3",
    "anchore/sbom-action": "v0",
    "sigstore/cosign-installer": "v3",
    "aquasecurity/trivy-action": "0.28.0",
    "gitleaks/gitleaks-action": "v2",
    "ossf/scorecard-action": "v2",
    "step-security/harden-runner": "v2",
    "ruby/setup-ruby": "v1",
    "dtolnay/rust-toolchain": "stable",
    "shivammathur/setup-php": "v2",
}

#: ecosystem -> setup action + default runtime version + version kwarg
SETUP_ACTIONS: dict[str, dict[str, str]] = {
    "python": {"action": "actions/setup-python", "kwarg": "python-version", "default": "3.12"},
    "node": {"action": "actions/setup-node", "kwarg": "node-version", "default": "20"},
    "go": {"action": "actions/setup-go", "kwarg": "go-version", "default": "stable"},
    "java": {"action": "actions/setup-java", "kwarg": "java-version", "default": "17"},
    "csharp": {"action": "actions/setup-dotnet", "kwarg": "dotnet-version", "default": "8.0.x"},
    "ruby": {"action": "ruby/setup-ruby", "kwarg": "ruby-version", "default": "3.3"},
    "rust": {"action": "dtolnay/rust-toolchain", "kwarg": "toolchain", "default": "stable"},
    "php": {"action": "shivammathur/setup-php", "kwarg": "php-version", "default": "8.3"},
}


#: Default with-args when a tool is installed via its official action.
ACTION_DEFAULT_ARGS: dict[str, dict[str, str]] = {
    "aquasecurity/trivy-action": {
        "scan-type": "fs",
        "scan-ref": ".",
        "severity": "HIGH,CRITICAL",
        "exit-code": "1",
    },
    "gitleaks/gitleaks-action": {},
    "anchore/sbom-action": {
        "path": ".",
        "format": "cyclonedx-json",
        "output-file": "sbom.cyclonedx.json",
    },
    "sigstore/cosign-installer": {"cosign-release": "v2.2.4"},
}


def action_ref(name: str) -> str:
    """Return the pinned `name@version` reference for a known action."""
    version = KNOWN_ACTION_VERSIONS.get(name)
    if version is None:
        raise KeyError(f"no pinned version known for action '{name}'")
    return f"{name}@{version}"


def is_approved_action(uses: str, prefixes: list[str]) -> bool:
    return any(uses.startswith(prefix) for prefix in prefixes)


def setup_action_for_ecosystem(ecosystem: str) -> dict[str, str] | None:
    return SETUP_ACTIONS.get(ecosystem)
