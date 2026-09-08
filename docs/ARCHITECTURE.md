# CI Agent — Architecture

This document describes the production system built from
`ci_agent_production_architecture_report.pdf` (§4 modular monolith, §13 module
contracts). It is the map of the code: every section points at the modules that
implement it.

## 1. System at a glance

```
                        ┌────────────────────────────────────────────┐
                        │  UI (React + Vite, ui/)                    │
                        │  Dashboard · Run detail · Approvals ·      │
                        │  Knowledge · Policies · Health             │
                        └──────────────────┬─────────────────────────┘
                                           │  REST /api/v1  (+ /healthz /readyz /metrics)
                        ┌──────────────────▼─────────────────────────┐
                        │  API (FastAPI, backend/src/ci_agent/api/)  │
                        │  runs · approvals · knowledge · policies   │
                        └──────────────────┬─────────────────────────┘
                                           │
                        ┌──────────────────▼─────────────────────────┐
                        │  Orchestrator (agent/orchestrator.py)      │
                        │  one async state machine per run:          │
                        └──────┬───┬───┬───┬───┬───┬───┬───┬───┬────┘
                               │   │   │   │   │   │   │   │   │
              ┌────────────────┘   │   │   │   │   │   │   │   └──────────────┐
              ▼                    ▼   ▼   ▼   ▼   ▼   ▼   ▼                    ▼
        discovery              planner │ pipeline │ validation │ security  integrations
        (clone +               (intent │ (IR +    │ (schema +  │ (scans    (GitHub PRs,
         inspect)               +plan) │ render)  │ actionlint │  gating)   syft/cosign/
                                                               + repair)  chainloop)
              │                    │   │   │   │   │   │   │                    │
              └────────────────┬───┴───┴───┴───┴───┴───┴───┴────────────────────┘
                               ▼
              ┌──────────────────────────────────────────────────────────────┐
              │  Cross-cutting: policy (OPA + local mirror) · knowledge      │
              │  (grounded catalog) · evidence (immutable store + SQLite) ·  │
              │  llm (Foundry/OpenAI + deterministic fallback) · execution   │
              │  (sandbox) · observability (logs + Prometheus) · security    │
              │  (API key auth, redaction, secret storage)                   │
              └──────────────────────────────────────────────────────────────┘

External services (see LOCAL_SERVICES.md + docker-compose.yml):
  PostgreSQL (evidence DB) · Redis (cache) · OPA server (policy decisions) ·
  Prometheus (metrics, optional profile)
```

## 2. Request lifecycle (one run)

1. `POST /api/v1/runs` validates the payload (`repo_url` host allow-list,
   platform enum), creates the run row + evidence directory, and schedules the
   orchestrator as a background task. Returns `202 {run_id}`.
2. **Discovery** (`discovery/repo.py`): shallow-clones the repo at the pinned
   SHA (or fixed branch) into an isolated work dir; records sha, default
   branch, languages, package managers, test frameworks, existing CI.
3. **Risk classification** (`agent/risks.py`): LOW / MEDIUM / HIGH from publish
   intent, deploy jobs, secret touch, and target branch. HIGH risk forces an
   approval gate before any mutation.
4. **Intent parsing** (`planner/intent.py`): deterministic parser first
   (capabilities, prohibited tools, deployment target, branches), LLM used only
   as an enrichment fallback, validated against `llm/schemas.py`.
5. **Plan construction** (`planner/plan.py`): every tool must resolve to a
   grounded knowledge record (`knowledge/retrieve.py`); unknown or
   prohibited tools are rejected or replaced with an allow-listed equivalent.
6. **Policy evaluation** (`policy/engine.py` → `policy/opa.py`, fallback
   `policy/local.py`): the full plan + intent + repo facts are sent to OPA
   (Rego in `deploy/opa/store/policies/`, data in `deploy/opa/store/data.json`).
   Verdicts: `ALLOW`, `ALLOW_WITH_APPROVAL`, `DENY` (fail-closed on OPA error).
7. **Pipeline build + render** (`pipeline/ir.py`, `pipeline/{github,azure,gitlab,jenkins}.py`):
   plan → validated Pipeline IR (pydantic schema) → platform YAML. Action refs
   are tag-pinned; `backend/scripts/pin_actions.py` hardens them to SHAs.
8. **Validation** (`validation/runner.py`): IR schema, rendered-YAML schema,
   workflow-security rules, and OSS actionlint when installed. On failure,
   `execution/repair.py` applies bounded deterministic fixes (≤3 attempts), then
   the run fails honestly — never silently.
9. **Security + supply chain**: secret scan (gitleaks or builtin fallback),
   SAST/SCA/container/IaC scanners when present, SBOM via Syft, signing via
   Cosign, attestation via Chainloop — each step runs only when its capability
   was requested; every result carries `provenance.runner` so skipped/fallback
   steps are visible (`builtin | binary | fallback | skipped`).
10. **Approval gate**: `awaiting_approval` pauses before publish whenever the
    policy demands it, risk is HIGH, or the caller set `require_approval`.
    `POST /runs/{id}/approve` records the decision immutably.
11. **Publish** (`integrations/github.py`): branch → commit → PR → check
    aggregation → merge recommendation. PR checks can be refreshed and will
    block the merge recommendation until green.
12. **Evidence**: every step appends JSONL events; the finished run writes an
    immutable evidence bundle (inputs, intent, plan, policy input/output, IR,
    YAML, validation, approvals) served at `GET /runs/{id}/evidence`.

## 3. Module contracts (PDF §13)

| Module | Owns | Must never |
|---|---|---|
| `discovery` | clone, pin SHA, inspect repo | execute repo code, touch network beyond git |
| `planner` | intent + grounded plan | invent tools/versions (must cite knowledge) |
| `policy` | ALLOW/APPROVAL/DENY verdicts | allow on engine error (fail closed) |
| `pipeline` | IR schema + platform renderers | emit unpinned actions / unvalidated IR |
| `validation` | schema + security + actionlint | pass silently (provenance always recorded) |
| `execution` | sandbox + bounded repair | unbounded retries, network in sandbox |
| `security` | scans + gating verdicts | block on missing scanner without provenance |
| `integrations` | GitHub/Syft/Cosign/Chainloop | mutate a repo without an approval when required |
| `knowledge` | grounded tool catalog | return unverified claims as facts |
| `evidence` | immutable run record | rewrite history (append-only) |
| `llm` | optional enrichment | be required for a correct run (fallback first) |
| `observability` | structured logs + metrics | log secrets (redaction enforced) |

## 4. Data stores

- **SQLite (dev/tests) / PostgreSQL (compose + prod)**: runs, events, approvals,
  knowledge records — see `common/models.py`, `common/db.py`. Postgres runs as
  the `db` service; schema is created at startup (`create_all`).
- **Evidence directory** (`CI_AGENT_DATA_DIR`): append-only JSONL event logs and
  per-run evidence bundles (`evidence/store.py`).
- **Work directory** (`AGENT_WORK_DIR`): per-run clones, sandboxes, generated
  YAML. Ephemeral; safe to wipe.
- **Redis** (`REDIS_URL`, optional): cache for discovery metadata and rate
  limiting; the API runs fine without it.
- **OPA bundle** (`deploy/opa/store/`): Rego policies + `data.json` catalog.
  Mounted read-only into the OPA server and into the API (local mirror).

## 5. Failure semantics

- Policy engine error → **DENY** (fail closed), run marked `denied`.
- Missing optional binary (actionlint, gitleaks, syft, …) → step records
  `provenance.runner: skipped|fallback`, run continues.
- Validation failure after ≤3 repairs → run `failed` with validator output.
- HIGH-risk or policy-demanded approval → `awaiting_approval` (pause, no
  mutation) until a human decides.
- LLM unavailable → deterministic fallback; the pipeline never depends on it.

## 6. Configuration

Single source of truth: `backend/src/ci_agent/config.py` (pydantic settings,
every field has an env alias). `config/agent.yaml.example` documents the file
form. See `docs/API.md` for the env-var table and `LOCAL_SERVICES.md` for the
compose stack.
