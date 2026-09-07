"""Core data contracts (PDF §11). Stable typed objects between modules.

The LLM may *fill* structured fields, but deterministic code validates them.
Every contract carries evidence so decisions stay traceable (§3).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .util import sha256_json, utcnow


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=False)


# ---------------------------------------------------------------- enums
class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    PUBLISHING = "publishing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"


class Platform(str, Enum):
    GITHUB = "github"
    AZURE = "azure"
    GITLAB = "gitlab"
    JENKINS = "jenkins"


class Capability(str, Enum):
    LINT = "lint"
    FORMAT = "format"
    TEST = "test"
    SAST = "sast"
    SCA = "sca"
    SECRETS = "secrets"
    CONTAINER_SCAN = "container-scan"
    IAC_SCAN = "iac-scan"
    BUILD = "build"
    DOCKER_BUILD = "docker-build"
    SBOM = "sbom"
    SIGN = "sign"
    DEPLOY = "deploy"


# ------------------------------------------------------------- evidence
class EvidenceItem(StrictModel):
    source_type: str = Field(description="repo_file | doc_page | package_metadata | policy_rule | tool_output | llm | seed")
    source: str = Field(description="file path, URL, rule id, or tool name")
    detail: str = ""
    excerpt_hash: str = ""
    retrieved_at: datetime = Field(default_factory=utcnow)


# ------------------------------------------------- repository context
class RepoLanguage(StrictModel):
    name: str
    version_constraint: str = ""
    package_manager: str = ""
    evidence: list[EvidenceItem] = Field(default_factory=list)


class TestSetup(StrictModel):
    framework: str = ""
    command: str = ""
    config_files: list[str] = Field(default_factory=list)


class ExistingCI(StrictModel):
    platform: str
    path: str
    triggers: list[str] = Field(default_factory=list)


class RepositoryContext(StrictModel):
    repo_url: str
    revision: str = ""
    commit_sha: str = ""
    default_branch: str = ""
    is_fork: bool = False
    languages: list[RepoLanguage] = Field(default_factory=list)
    package_managers: list[str] = Field(default_factory=list)
    dependency_files: list[str] = Field(default_factory=list)
    lockfiles: list[str] = Field(default_factory=list)
    test_setups: list[TestSetup] = Field(default_factory=list)
    has_dockerfile: bool = False
    dockerfiles: list[str] = Field(default_factory=list)
    existing_ci: list[ExistingCI] = Field(default_factory=list)
    total_files: int = 0
    licenses: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    discovered_at: datetime = Field(default_factory=utcnow)
    context_hash: str = ""

    def compute_hash(self) -> str:
        payload = self.model_dump(exclude={"context_hash", "evidence", "discovered_at"})
        return sha256_json(payload)


# ------------------------------------------------------------- knowledge
class ToolInstall(StrictModel):
    type: str = Field(description="pip | npm | go | cargo | binary | docker | action | apt | brew")
    command: str


class KnowledgeSource(StrictModel):
    url: str
    source_type: str = "doc_page"
    retrieved_at: datetime = Field(default_factory=utcnow)
    evidence: list[str] = Field(default_factory=list)


class KnowledgeRecord(StrictModel):
    tool: str
    capabilities: list[str] = Field(default_factory=list)
    ecosystems: list[str] = Field(default_factory=list)
    install_methods: list[ToolInstall] = Field(default_factory=list)
    ci_integrations: list[str] = Field(default_factory=list)
    versions: list[str] = Field(default_factory=list)
    source: KnowledgeSource | None = None
    confidence: float = 0.5
    record_hash: str = ""

    def compute_hash(self) -> str:
        payload = {
            "tool": self.tool,
            "capabilities": sorted(self.capabilities),
            "ecosystems": sorted(self.ecosystems),
            "versions": sorted(self.versions),
        }
        return sha256_json(payload)


# ----------------------------------------------------------------- intent
class UserIntent(StrictModel):
    """Structured request (PDF §5 step 5). Produced by LLM structured outputs
    (or the deterministic fallback) and validated before planning."""

    platform: str = "github"
    capabilities: list[str] = Field(default_factory=list)
    deployment_target: str = ""
    constraints: list[str] = Field(default_factory=list)
    prohibited_tools: list[str] = Field(default_factory=list)
    required_controls: list[str] = Field(default_factory=list)
    trigger_branches: list[str] = Field(default_factory=list)
    raw_request: str = ""
    planner: str = Field(default="", description="model name or 'deterministic-fallback'")


# ------------------------------------------------------------------- plan
class PlannedTool(StrictModel):
    name: str
    version: str = "unknown"
    capability: str = ""
    reason: str = ""
    knowledge_refs: list[str] = Field(default_factory=list)


class PlannedAction(StrictModel):
    uses: str
    pinned: bool = False
    version: str = ""


class CandidatePlan(StrictModel):
    tools: list[PlannedTool] = Field(default_factory=list)
    actions: list[PlannedAction] = Field(default_factory=list)
    permissions: dict[str, str] = Field(default_factory=dict)
    licenses: list[str] = Field(default_factory=list)
    has_deploy_job: bool = False
    touches_security: bool = False
    removes_security: bool = False
    cloud_oidc: bool = False
    notes: list[str] = Field(default_factory=list)

    def compute_hash(self) -> str:
        return sha256_json(self.model_dump())


# ----------------------------------------------------------------- policy
class PolicyFinding(StrictModel):
    rule: str
    message: str


class PolicyDecision(StrictModel):
    decision: Decision = Decision.DENY
    deny: list[PolicyFinding] = Field(default_factory=list)
    approval_reasons: list[PolicyFinding] = Field(default_factory=list)
    evaluator: str = Field(description="opa-server | local | local-fallback")
    evaluated_at: datetime = Field(default_factory=utcnow)
    bundle_version: str = "1.0"


# ------------------------------------------------------------ pipeline IR
class IRStep(StrictModel):
    id: str
    name: str
    capability: str = ""
    tool: str = ""
    run: str = ""
    uses: str = ""
    with_args: dict[str, Any] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    condition: str = ""


class IRJob(StrictModel):
    id: str
    name: str
    runs_on: str = "ubuntu-latest"
    needs: list[str] = Field(default_factory=list)
    permissions: dict[str, str] = Field(default_factory=dict)
    steps: list[IRStep] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    environment: str = ""


class IRGate(StrictModel):
    id: str
    type: str = Field(description="approval | policy | validation")
    config: dict[str, Any] = Field(default_factory=dict)


class PipelineIR(StrictModel):
    """Versioned intermediate representation (PDF §4). Renderers consume this;
    the LLM never writes final YAML or shell directly."""

    version: str = "1.0"
    platform: str = "github"
    name: str = "ci"
    triggers: dict[str, Any] = Field(default_factory=dict)
    jobs: list[IRJob] = Field(default_factory=list)
    permissions: dict[str, str] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    gates: list[IRGate] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def compute_hash(self) -> str:
        return sha256_json(self.model_dump())


# ------------------------------------------------------------- validation
class ValidationFinding(StrictModel):
    validator: str
    version: str = ""
    level: Literal["error", "warning", "info"] = "error"
    message: str = ""
    file: str = ""
    line: int = 0
    remediation: str = ""


class ValidationResult(StrictModel):
    validator: str
    version: str = ""
    passed: bool = True
    errors: list[ValidationFinding] = Field(default_factory=list)
    warnings: list[ValidationFinding] = Field(default_factory=list)
    duration_ms: int = 0
    provenance: dict[str, str] = Field(default_factory=dict)


# ------------------------------------------------------------------ runs
class RunOptions(StrictModel):
    platform: str = "github"
    revision: str = ""
    publish: bool = False
    target_branch: str = ""
    base_branch: str = ""
    pr_title: str = ""
    require_approval: bool = False
    capabilities: list[str] = Field(default_factory=list)
    deployment_target: str = ""
    workflow_filename: str = ""


class RunEvent(StrictModel):
    run_id: str
    seq: int = 0
    step: str = ""
    level: str = "info"
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class ApprovalInput(StrictModel):
    approver: str = "unknown"
    decision: Literal["approve", "reject"] = "approve"
    reason: str = ""


class ApprovalRecord(StrictModel):
    run_id: str
    approver: str
    decision: str
    reason: str = ""
    decided_at: datetime = Field(default_factory=utcnow)


class CostRecord(StrictModel):
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd_estimate: float = 0.0


# ------------------------------------------------------- decision evidence
class DecisionEvidence(StrictModel):
    """Immutable record of what was known/decided/generated/approved (§11)."""

    run_id: str
    request: str = ""
    repo_url: str = ""
    repo_revision: str = ""
    commit_sha: str = ""
    context_hash: str = ""
    knowledge_refs: list[str] = Field(default_factory=list)
    model: str = ""
    plan_hash: str = ""
    policy: PolicyDecision | None = None
    risk_level: str = "low"
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    validator_outputs: list[ValidationResult] = Field(default_factory=list)
    approval: ApprovalRecord | None = None
    final_action: str = ""
    costs: list[CostRecord] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    evidence_hash: str = ""

    def compute_hash(self) -> str:
        return sha256_json(self.model_dump(exclude={"evidence_hash"}))


# --------------------------------------------------------------- security
class SecretFinding(StrictModel):
    file: str
    line: int = 0
    rule: str = ""
    fingerprint: str = Field(description="hash of the matched secret, never the secret itself")


class SecretScanResult(StrictModel):
    scanner: str
    passed: bool = True
    findings: list[SecretFinding] = Field(default_factory=list)
    files_scanned: int = 0
    provenance: dict[str, str] = Field(default_factory=dict)


class VulnFinding(StrictModel):
    package: str
    installed_version: str = ""
    fixed_version: str = ""
    vuln_id: str = ""
    severity: str = ""
    summary: str = ""
    source: str = ""


class SCAResult(StrictModel):
    scanner: str
    passed: bool = True
    findings: list[VulnFinding] = Field(default_factory=list)
    packages_scanned: int = 0
    provenance: dict[str, str] = Field(default_factory=dict)


class SASTResult(StrictModel):
    scanner: str
    passed: bool = True
    findings: list[dict[str, Any]] = Field(default_factory=list)
    files_scanned: int = 0
    provenance: dict[str, str] = Field(default_factory=dict)


# ------------------------------------------------------------ supply chain
class SBOMResult(StrictModel):
    generator: str = "syft"
    format: str = "cyclonedx-json"
    package_count: int = 0
    sbom_path: str = ""
    digest: str = ""
    provenance: dict[str, str] = Field(default_factory=dict)


class SignResult(StrictModel):
    signer: str = "cosign"
    artifact: str = ""
    signature_path: str = ""
    certificate: str = ""
    digest: str = ""
    provenance: dict[str, str] = Field(default_factory=dict)
