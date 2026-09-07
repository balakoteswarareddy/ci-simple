"""Phase 0: central configuration.

Precedence: environment variables > optional YAML file (CI_AGENT_CONFIG_FILE)
> built-in defaults. YAML is only a convenience for static deployments; every
value here is also settable via env (see .env.example).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_ALLOWED_COMMANDS = (
    "git,python,python3,pytest,pip,node,npm,npx,go,cargo,syft,cosign,"
    "actionlint,gitleaks,trivy,semgrep,osv-scanner,docker"
)


def _yaml_values() -> dict[str, Any]:
    """Read the optional YAML config, skipping any key already set via env."""
    path = os.environ.get("CI_AGENT_CONFIG_FILE", "")
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    def env_set(*names: str) -> bool:
        return any(n in os.environ for n in names)

    flat: dict[str, Any] = {}
    agent = data.get("agent", {}) or {}
    if "max_repair_attempts" in agent and not env_set("MAX_REPAIR_ATTEMPTS"):
        flat["max_repair_attempts"] = agent["max_repair_attempts"]
    if "default_platform" in agent and not env_set("DEFAULT_PLATFORM"):
        flat["default_platform"] = agent["default_platform"]
    if "require_approval_default" in agent and not env_set("REQUIRE_APPROVAL_DEFAULT"):
        flat["require_approval_default"] = agent["require_approval_default"]
    discovery = data.get("discovery", {}) or {}
    if "clone_depth" in discovery and not env_set("CLONE_DEPTH"):
        flat["clone_depth"] = discovery["clone_depth"]
    if "clone_timeout_seconds" in discovery and not env_set("CLONE_TIMEOUT_SECONDS"):
        flat["clone_timeout_seconds"] = discovery["clone_timeout_seconds"]
    knowledge = data.get("knowledge", {}) or {}
    if "cache_ttl_hours" in knowledge and not env_set("KNOWLEDGE_CACHE_TTL_HOURS"):
        flat["knowledge_cache_ttl_hours"] = knowledge["cache_ttl_hours"]
    policy = data.get("policy", {}) or {}
    if "timeout_seconds" in policy and not env_set("OPA_TIMEOUT_SECONDS"):
        flat["opa_timeout_seconds"] = policy["timeout_seconds"]
    sandbox = data.get("sandbox", {}) or {}
    if "mode" in sandbox and not env_set("SANDBOX_MODE"):
        flat["sandbox_mode"] = sandbox["mode"]
    if "timeout_seconds" in sandbox and not env_set("SANDBOX_TIMEOUT_SECONDS"):
        flat["sandbox_timeout_seconds"] = sandbox["timeout_seconds"]
    if "allow_network" in sandbox and not env_set("SANDBOX_ALLOW_NETWORK"):
        flat["sandbox_allow_network"] = sandbox["allow_network"]
    if "allowed_commands" in sandbox and not env_set("SANDBOX_ALLOWED_COMMANDS"):
        cmds = sandbox["allowed_commands"]
        flat["sandbox_allowed_commands"] = ",".join(cmds) if isinstance(cmds, list) else cmds
    return flat


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = Field(default="dev", alias="CI_AGENT_ENV")
    data_dir: str = Field(default="./data", alias="CI_AGENT_DATA_DIR")
    work_dir: str = Field(default="", alias="AGENT_WORK_DIR")
    api_key: str = Field(default="", alias="CI_AGENT_API_KEY")
    base_url: str = Field(default="http://localhost:8000", alias="CI_AGENT_BASE_URL")
    cors_origins: str = Field(default="http://localhost:5173,http://localhost:8080", alias="CORS_ORIGINS")

    database_url: str = Field(default="sqlite:///./data/ci-agent.db", alias="DATABASE_URL")
    redis_url: str = Field(default="", alias="REDIS_URL")

    opa_url: str = Field(default="", alias="OPA_URL")
    opa_timeout_seconds: int = Field(default=10, alias="OPA_TIMEOUT_SECONDS")
    opa_bundle_dir: str = Field(default="./deploy/opa/store", alias="OPA_BUNDLE_DIR")
    policy_decision_path: str = Field(default="ciagent/policy/decision", alias="POLICY_DECISION_PATH")

    llm_provider: str = Field(default="", alias="LLM_PROVIDER")
    foundry_endpoint: str = Field(default="", alias="FOUNDRY_ENDPOINT")
    foundry_api_key: str = Field(default="", alias="FOUNDRY_API_KEY")
    foundry_deployment: str = Field(default="gpt-4o-mini", alias="FOUNDRY_DEPLOYMENT")
    foundry_api_version: str = Field(default="2024-10-21", alias="FOUNDRY_API_VERSION")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    llm_max_tokens: int = Field(default=4000, alias="LLM_MAX_TOKENS")
    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")

    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    github_api_url: str = Field(default="https://api.github.com", alias="GITHUB_API_URL")
    allowed_git_hosts: str = Field(default="github.com", alias="ALLOWED_GIT_HOSTS")
    allow_local_repos: bool = Field(default=False, alias="ALLOW_LOCAL_REPOS")

    knowledge_cache_ttl_hours: int = Field(default=24, alias="KNOWLEDGE_CACHE_TTL_HOURS")
    knowledge_fetch_timeout_seconds: int = Field(default=20, alias="KNOWLEDGE_FETCH_TIMEOUT_SECONDS")
    knowledge_allow_hosts: str = Field(
        default="docs.python.org,nodejs.org,go.dev,doc.rust-lang.org,github.com,"
        "raw.githubusercontent.com,docs.github.com,osv.dev,api.osv.dev",
        alias="KNOWLEDGE_ALLOW_HOSTS",
    )

    sandbox_mode: str = Field(default="local", alias="SANDBOX_MODE")
    sandbox_docker_image: str = Field(default="python:3.11-slim", alias="SANDBOX_DOCKER_IMAGE")
    sandbox_timeout_seconds: int = Field(default=600, alias="SANDBOX_TIMEOUT_SECONDS")
    sandbox_allow_network: bool = Field(default=False, alias="SANDBOX_ALLOW_NETWORK")
    sandbox_allowed_commands: str = Field(default=_DEFAULT_ALLOWED_COMMANDS, alias="SANDBOX_ALLOWED_COMMANDS")

    cosign_key_ref: str = Field(default="", alias="COSIGN_KEY_REF")
    chainloop_control_plane: str = Field(default="", alias="CHAINLOOP_CONTROL_PLANE")
    chainloop_robot_account: str = Field(default="", alias="CHAINLOOP_ROBOT_ACCOUNT")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")
    metrics_enabled: bool = Field(default=True, alias="METRICS_ENABLED")

    max_repair_attempts: int = Field(default=3, alias="MAX_REPAIR_ATTEMPTS")
    default_platform: str = Field(default="github", alias="DEFAULT_PLATFORM")
    require_approval_default: bool = Field(default=False, alias="REQUIRE_APPROVAL_DEFAULT")
    clone_depth: int = Field(default=50, alias="CLONE_DEPTH")
    clone_timeout_seconds: int = Field(default=120, alias="CLONE_TIMEOUT_SECONDS")

    # -- derived helpers -------------------------------------------------
    @property
    def resolved_data_dir(self) -> Path:
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def resolved_work_dir(self) -> Path:
        base = Path(self.work_dir) if self.work_dir else self.resolved_data_dir / "work"
        base.mkdir(parents=True, exist_ok=True)
        return base

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_git_hosts_list(self) -> list[str]:
        return [h.strip().lower() for h in self.allowed_git_hosts.split(",") if h.strip()]

    @property
    def knowledge_allow_hosts_list(self) -> list[str]:
        return [h.strip().lower() for h in self.knowledge_allow_hosts.split(",") if h.strip()]

    @property
    def sandbox_allowed_commands_list(self) -> list[str]:
        return [c.strip() for c in self.sandbox_allowed_commands.split(",") if c.strip()]

    @property
    def llm_model_name(self) -> str:
        if self.llm_provider == "azure-foundry" or (not self.llm_provider and self.foundry_endpoint):
            return self.foundry_deployment
        return self.openai_model

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "none":
            return False
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        if self.llm_provider == "azure-foundry":
            return bool(self.foundry_endpoint and self.foundry_api_key)
        # auto-detect
        return bool((self.foundry_endpoint and self.foundry_api_key) or self.openai_api_key)

    @property
    def effective_llm_provider(self) -> str:
        if self.llm_provider in ("azure-foundry", "openai", "none"):
            return self.llm_provider
        if self.foundry_endpoint and self.foundry_api_key:
            return "azure-foundry"
        if self.openai_api_key:
            return "openai"
        return "none"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(**_yaml_values())


def reset_settings() -> None:
    get_settings.cache_clear()
