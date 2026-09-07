"""Canonical run commands per tool (PDF §4 renderers are deterministic).

The planner grounds tool *selection* in knowledge; this table grounds the
*invocation* so the LLM never invents CLI flags. Commands stay shell-simple
and portable across linux runners.
"""
from __future__ import annotations

#: tool -> argv-style command template. `{args}` placeholders are filled by IR.
TOOL_COMMANDS: dict[str, str] = {
    "ruff": "ruff check .",
    "black": "black --check .",
    "flake8": "flake8 .",
    "eslint": "npx eslint .",
    "prettier": "npx prettier --check .",
    "pytest": "pytest -q",
    "jest": "npx jest --ci",
    "vitest": "npx vitest run",
    "phpunit": "vendor/bin/phpunit",
    "rspec": "bundle exec rspec",
    "go-test": "go test ./...",
    "cargo-test": "cargo test",
    "semgrep": "semgrep scan --config auto --error .",
    "bandit": "bandit -r . -q",
    "gosec": "gosec ./...",
    "trivy": "trivy fs --severity HIGH,CRITICAL --exit-code 1 .",
    "gitleaks": "gitleaks detect --source . --verbose --exit-code 1",
    "trufflehog": "trufflehog filesystem . --only-verified --fail",
    "osv-scanner": "osv-scanner -r .",
    "pip-audit": "pip-audit",
    "npm-audit": "npm audit --audit-level=moderate",
    "cargo-audit": "cargo audit",
    "syft": "syft . -o cyclonedx-json=sbom.cyclonedx.json",
    "cosign": "cosign sign-blob --yes sbom.cyclonedx.json --output-signature sbom.sig --output-certificate sbom.pem",
    "actionlint": "actionlint",
    "shellcheck": "git ls-files '*.sh' | xargs -r shellcheck",
    "hadolint": "hadolint Dockerfile",
    "yamllint": "yamllint .",
    "checkov": "checkov -d . --quiet --compact",
    "kics": "kics scan -p . --no-progress --exclude-severities INFO,LOW",
    "docker": "docker build -t app:ci .",
}

#: tool -> condition guard so optional checks no-op cleanly on repos that
#: lack the relevant files. Renderers translate these per platform.
TOOL_CONDITIONS: dict[str, str] = {
    "shellcheck": "hashFiles('**/*.sh') != ''",
    "hadolint": "hashFiles('**/Dockerfile*') != ''",
    "actionlint": "hashFiles('.github/workflows/*.yml', '.github/workflows/*.yaml') != ''",
}

#: install command overrides when the knowledge record has no install method.
FALLBACK_INSTALL: dict[str, str] = {
    "ruff": "pip install ruff",
    "black": "pip install black",
    "flake8": "pip install flake8",
    "pytest": "pip install pytest",
    "bandit": "pip install bandit",
    "pip-audit": "pip install pip-audit",
    "yamllint": "pip install yamllint",
    "checkov": "pip install checkov",
    "eslint": "npm install --save-dev eslint",
    "prettier": "npm install --save-dev prettier",
    "jest": "npm install --save-dev jest",
    "vitest": "npm install --save-dev vitest",
}


def command_for(tool: str) -> str:
    if tool not in TOOL_COMMANDS:
        raise KeyError(f"no canonical command for tool '{tool}' — refusing to invent one")
    return TOOL_COMMANDS[tool]


def condition_for(tool: str) -> str:
    return TOOL_CONDITIONS.get(tool, "")
