# Phase map — PDF §9 acceptance coverage

The PDF builds the system in Phases 0–7. This file maps each phase to what was
delivered and where, so a reviewer can check §9 acceptance item by item.

## Phase 0 — Foundation, contracts, repo skeleton

- Repo layout (`backend/`, `ui/`, `deploy/`, `docs/`, `examples/`, `config/`),
  `Makefile`, `docker-compose.yml`, `config/agent.yaml.example`.
- Module contracts documented in `docs/ARCHITECTURE.md` (§3) per PDF §13.
- Shared primitives: `common/models.py` (Run, Event, Approval, KnowledgeRecord),
  `common/db.py` (SQLite/Postgres session), `common/util.py`, `config.py`
  (all settings, env-aliased), `observability/logging.py` (JSON logs),
  `observability/metrics.py` (Prometheus), `security/redact.py`.

## Phase 1 — Discovery + grounded knowledge

- `discovery/repo.py`: allow-listed clone, SHA pinning, language/manager/test/CI
  detection. Local paths only when `ALLOW_LOCAL_REPOS=true` (dev/tests).
- `knowledge/`: `schemas.py` (ToolRecord evidence model), `store.py`
  (SQLite-backed), `seeds.py` + `data/seed_tools.json` (31 curated tools),
  `retrieve.py` (capability/ecosystem/version resolution), `ingest.py`
  (allow-listed HTTPS fetch, claim verification, `POST /knowledge/ingest`,
  `POST /knowledge/refresh`).
- UI: Knowledge page (browse records, ingest URL, refresh-all).

## Phase 2 — Planning (intent → grounded plan)

- `planner/intent.py`: deterministic parser (capabilities, prohibited tools,
  deployment target, branches, publish intent); `llm/` (Foundry + OpenAI +
  deterministic fallback, `llm/schemas.py`-validated) for enrichment only.
- `planner/plan.py`: tool selection grounded in knowledge, action pinning,
  least-privilege permissions, risk flags (`has_deploy_job`,
  `touches_security`, `removes_security`, `cloud_oidc`).
- `agent/risks.py`: LOW/MEDIUM/HIGH classification; HIGH forces approval.
- `pipeline/explain.py`: markdown explanation citing plan + policy + validation.

## Phase 3 — Policy governance (OPA)

- Rego: `deploy/opa/store/policies/` (`main`, `tools`, `actions`,
  `permissions`, `licenses`, `governance`) + `main_test.rego`; data:
  `deploy/opa/store/data.json` (`approved`, `denied`, `limits`) — one file
  because OPA merges store-root JSON at the data root (see `docs/POLICY.md`).
- `policy/`: `catalog.py` (reads `data.json`), `opa.py` (HTTP client +
  `data_present()` mount guard), `local.py` (audited mirror for dev/tests),
  `engine.py` (fail-closed orchestration: ALLOW / ALLOW_WITH_APPROVAL / DENY).
- API: `POST /policies/evaluate` (ad-hoc), `GET /policies/catalog`; UI:
  Policies page. `/readyz` requires OPA health AND data loaded.
- CI (`agent-ci.yml`) starts a real OPA server and asserts a live ALLOW.

## Phase 4 — Pipeline IR + multi-platform renderers

- `pipeline/ir.py`: versioned pydantic IR (jobs/steps/artifacts/permissions).
- Renderers: `pipeline/github.py`, `azure.py`, `gitlab.py`, `jenkins.py`
  (+ `render.py` dispatcher, `commands.py` tool-command templates,
  `actions.py` pinned action refs, `patch.py` minimal-diff updates).
- `backend/scripts/pin_actions.py`: tags → immutable SHAs.
- Golden determinism tests: `backend/tests/golden/` (regen via `regen.py`
  after intentional change), evals dataset: `backend/tests/evals/`.

## Phase 5 — Validation, repair, security (§9 OSS reuse)

- `validation/`: `schema_checks.py` (IR + rendered YAML), `security_checks.py`
  (permissions, injection, secret hygiene), `actionlint.py` (OSS binary when
  installed), `runner.py` (all-results-with-provenance orchestration).
- `execution/repair.py`: bounded (≤3) deterministic repair loop.
- `execution/sandbox.py`: local/docker sandbox for untrusted commands.
- `security/` + `integrations/scanners.py`: gitleaks/semgrep/trivy/checkov via
  real CLIs when present, honest `skipped|fallback` provenance otherwise.
- `integrations/syft.py`, `cosign.py`, `chainloop.py`: SBOM, signing,
  attestation — each capability-gated with provenance.
- CI runs actionlint over `agent-ci.yml` itself (dogfooding).

## Phase 6 — Publish, approvals, evidence (§9 audit)

- `integrations/github.py`: branch → commit → PR → checks → merge
  recommendation; `POST /runs/{id}/checks/refresh`.
- `agent/orchestrator.py`: approval pause/resume; `routes/approvals.py` +
  `POST /runs/{id}/approve` record immutable decisions; UI Approvals page.
- `evidence/store.py`: append-only JSONL + immutable per-run bundles;
  `GET /runs/{id}/evidence`. Events: `GET /runs/{id}/events`.

## Phase 7 — API, UI, deployability (§9 multi-surface)

- API (`api/`): versioned `/api/v1` routers (runs, approvals, knowledge,
  policies), API-key auth (`security/auth.py`), CORS, `/healthz`, `/readyz`,
  `/metrics`, OpenAPI at `/docs`.
- UI (`ui/`): React + Vite + TS — Dashboard, New-run wizard, Run detail
  (11 tabs: overview → evidence), Approvals, Knowledge, Policies, Health.
  `Dockerfile` + `nginx.conf` for serving; dev proxy for `/api`.
- Deploy: root `docker-compose.yml` (db, redis, opa, api, ui, prometheus
  profile), `backend/Dockerfile` (syft/cosign/actionlint pins),
  `deploy/prometheus/prometheus.yml`, `deploy/opa/config.yaml`.
- Docs: `LOCAL_SERVICES.md` (every service + whole config), `docs/RUNBOOKS.md`
  (operate), `docs/THREAT_MODEL.md` (abuse cases), `docs/JENKINS_TESTING.md`
  (Jenkinsfile harness), `docs/API.md` (REST reference), ADRs in `docs/adr/`.

## §9 acceptance checklist

- [x] Phase 0–7 coverage — this file.
- [x] Pipeline IR — `pipeline/ir.py`, golden-tested.
- [x] OPA governance — Rego + data + engine + live CI check.
- [x] OSS reuse — actionlint, Syft, Cosign, Chainloop, gitleaks/semgrep/trivy/
      checkov integrations (real CLIs, never reimplemented).
- [x] Evidence/audit — append-only store + immutable bundles + events API.
- [x] Approval gates — policy/risk/manual triggers, immutable decisions, UI.
- [x] Multi-platform renderers — GitHub, Azure, GitLab, Jenkins (+ patch mode).
