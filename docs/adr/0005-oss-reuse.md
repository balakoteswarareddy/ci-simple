# ADR 0005 — Reuse OSS tools, never reimplement scanners

- Status: accepted
- Date: 2026-09-07
- Context: PDF §9 OSS reuse acceptance

## Decision

Workflow lint = actionlint, SBOM = Syft, signing = Cosign, attestation =
Chainloop, secrets/SAST/container/IaC = gitleaks/semgrep/trivy/checkov —
invoked as real CLIs via thin adapters (`validation/actionlint.py`,
`integrations/{syft,cosign,chainloop,scanners}.py`).

## Rationale

Scanners encode years of rules and CVE feeds; a home-grown reimplementation
would be worse on day one and stale forever. Thin adapters keep the agent's
surface small (parse exit codes + JSON) while every finding keeps the
upstream tool's authority and version in provenance.

## Consequences

- Binaries are pinned in `backend/Dockerfile` and CI (actionlint 1.7.7,
  syft v1.21.0, cosign v2.4.3, OPA 1.0.0).
- Missing binaries degrade honestly: `provenance.runner: skipped|fallback`,
  never silent success.
