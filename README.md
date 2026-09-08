# CI Agent — grounded CI generation with policy governance

Describe the CI you want; the agent inspects your repo, builds a plan grounded
in a verified tool catalog, evaluates it against OPA policy, renders a
least-privilege workflow for your platform, validates it (schema + security +
OSS actionlint), scans it, and — only with approval — opens a PR. Every step is
explained, every decision carries provenance, and the whole run is recorded as
immutable evidence.

Built phase-by-phase from `ci_agent_production_architecture_report.pdf`
(Phases 0–7; coverage map in `docs/PHASES.md`).

## Quick start

```bash
# full stack: postgres + redis + opa + api + ui
docker compose up --build -d        # or: make dev-up
curl localhost:8000/readyz | jq     # all checks green?
```

- UI: http://localhost:8080 — Dashboard, New-run wizard, Approvals, Knowledge, Policies, Health
- API docs: http://localhost:8000/docs · readiness: `/readyz` · metrics: `/metrics`
- OPA: http://localhost:8181 (`/v1/data/approved/tools` → 31 tools)

No docker? `make api-dev` (SQLite + local policy mirror) and `make ui-dev`
(Vite on :5173, proxies `/api` to :8000).

Create your first run (see `examples/sample-request.json`):

```bash
curl -s -X POST localhost:8000/api/v1/runs -H 'Content-Type: application/json' \
  -d @examples/sample-request.json
# → {"run_id":"run_…"}  then poll:  curl localhost:8000/api/v1/runs/<id> | jq '{status, policy: .policy.decision}'
```

## How it works

`request → discover (clone+inspect) → risk → intent → grounded plan → OPA verdict
→ Pipeline IR → platform YAML → validate (+bounded repair) → scan/SBOM/sign
→ approval gate → PR + checks → immutable evidence`

- **Grounded, not guessed**: the planner may only use tools/versions from the
  verified knowledge catalog (31 seeds + allow-listed ingest + refresh).
- **Policy-governed**: OPA (Rego in `deploy/opa/store/`) returns
  ALLOW / ALLOW_WITH_APPROVAL / DENY; any engine error fails closed.
- **Honest about gaps**: missing scanners/binaries are recorded as
  `skipped|fallback` provenance — never silent success.
- **Multi-platform**: GitHub, Azure, GitLab, Jenkins from one Pipeline IR
  (byte-pinned golden tests); `backend/scripts/pin_actions.py` hardens action
  tags to SHAs.
- **OSS where it matters**: actionlint, Syft, Cosign, Chainloop,
  gitleaks/semgrep/trivy/checkov — real CLIs, thin adapters.

## Repo map

| Path | Contents |
|---|---|
| `backend/src/ci_agent/` | API, orchestrator, planner, policy, pipeline, validation, integrations, knowledge, evidence, … |
| `backend/tests/` | unit + integration + golden + evals (`59 passed, 2 skipped`) |
| `ui/` | React + Vite + TS console (Dashboard … Health) |
| `deploy/opa/store/` | Rego policies + `data.json` catalog (single file — see `docs/POLICY.md`) |
| `deploy/prometheus/` | scrape config |
| `docker-compose.yml` | full local stack (db, redis, opa, api, ui, prometheus profile) |
| `LOCAL_SERVICES.md` | **every service + its whole config** (start here for ops) |
| `docs/` | ARCHITECTURE, PHASES (§9 map), POLICY, API, THREAT_MODEL, RUNBOOKS, JENKINS_TESTING, adr/ |
| `examples/` | sample request + Jenkins replay harness |
| `config/agent.yaml.example` | optional static config (env vars win) |

## Docs entry points

- Operator: `LOCAL_SERVICES.md` → `docs/RUNBOOKS.md` → `docs/API.md`
- Reviewer: `docs/PHASES.md` (§9 checklist) → `docs/ARCHITECTURE.md` → `docs/adr/`
- Policy author: `docs/POLICY.md` → `deploy/opa/store/policies/`
- Security: `docs/THREAT_MODEL.md`

## Test & verify

```bash
make test            # backend pytest + UI tsc/vite build
make test-golden     # byte-determinism goldens
make evals           # agent eval dataset
make opa-check       # opa check ./deploy/opa/store
make compose-check   # compose YAML valid without docker
```

Live-verified: a real server run against the Python fixture completes
`succeeded` with policy `ALLOW`, all validators passing with provenance,
32 queued→completed events, and a downloadable evidence bundle.
