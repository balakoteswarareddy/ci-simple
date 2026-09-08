# REST API reference

Base URL (dev): `http://localhost:8000`. Interactive docs: `/docs`
(OpenAPI), `/redoc`. Auth: `X-API-Key` header when `CI_AGENT_API_KEY` is set;
actor identity via `X-Actor` (recorded on approval decisions).

## Ops

| Method | Path | Description |
|---|---|---|
| GET | `/healthz` | Liveness: `{status, version}` |
| GET | `/readyz` | Readiness: `{ready, checks:{database, opa, knowledge, llm}}` |
| GET | `/metrics` | Prometheus exposition |

## Runs

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/runs` | Create run → `202 {run_id}` |
| GET | `/api/v1/runs?status=` | List runs (newest first, filterable) |
| GET | `/api/v1/runs/{id}` | Full detail: intent, plan, policy, IR, validation, security, supply chain, publish, explanation |
| GET | `/api/v1/runs/{id}/events?after=` | JSONL-backed event stream (poll with `after` seq) |
| GET | `/api/v1/runs/{id}/yaml` | `{filename, content}` rendered workflow |
| GET | `/api/v1/runs/{id}/evidence` | Immutable evidence bundle |
| POST | `/api/v1/runs/{id}/approve` | `{decision: approve\|reject, reason?}` |
| POST | `/api/v1/runs/{id}/checks/refresh` | Re-poll PR checks, recompute merge recommendation |

### Create-run payload

```jsonc
{
  "repo_url": "https://github.com/org/repo",   // allow-listed host (or local path if enabled)
  "request": "Create CI: run pytest, ruff, bandit. Do not use Semgrep.",
  "options": {
    "platform": "github",          // github | azure | gitlab | jenkins
    "revision": "",                // branch/tag/SHA, default branch if empty
    "publish": false,              // create branch + commit + PR when true
    "target_branch": "",           // default: ci-agent/<run-id>
    "base_branch": "",             // default: repo default branch
    "pr_title": "",
    "require_approval": false,     // force a human gate
    "capabilities": ["lint"]       // optional UX override; parsed from request when empty
  }
}
```

### Run statuses

`queued → running → (awaiting_approval → running) → succeeded | failed | denied | cancelled`

## Approvals

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/approvals/pending` | `{pending[]}` runs waiting on humans |

(Decisions are posted to `/runs/{id}/approve`.)

## Knowledge

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/knowledge/tools` | `{tools[]}` catalog names |
| GET | `/api/v1/knowledge/stats` | `{total, fresh_records, seed_records, …}` |
| GET | `/api/v1/knowledge/tools/{name}` | Full grounded record with evidence |
| POST | `/api/v1/knowledge/ingest` | `{url, hint?}` — fetch + verify + store |
| POST | `/api/v1/knowledge/refresh` | Re-fetch all refreshable sources |

## Policies

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/policies/catalog` | `{tools, capabilities, action_prefixes, denied_licenses, protected_branches, known_permissions}` |
| POST | `/api/v1/policies/evaluate` | Ad-hoc verdict for an `{intent, plan, repo, risk_level, …}` payload |

## curl examples

```bash
# create
curl -s -X POST localhost:8000/api/v1/runs -H 'Content-Type: application/json' \
  -d '{"repo_url":"https://github.com/org/repo","request":"CI with pytest and ruff","options":{"platform":"github"}}'

# poll
curl -s localhost:8000/api/v1/runs/<id> | jq '{status, risk_level, policy: .policy.decision}'

# approve
curl -s -X POST localhost:8000/api/v1/runs/<id>/approve -H 'Content-Type: application/json' \
  -H 'X-Actor: reviewer' -d '{"decision":"approve","reason":"looks least-privilege"}'

# evidence
curl -s localhost:8000/api/v1/runs/<id>/evidence | jq .
```

## Environment reference (selection; full list in `config.py`)

| Variable | Default | Purpose |
|---|---|---|
| `CI_AGENT_ENV` | `dev` | `dev` \| `prod` (strictness toggles) |
| `CI_AGENT_API_KEY` | _(empty = open)_ | required `X-API-Key` when set |
| `DATABASE_URL` | sqlite `./data/ci-agent.db` | postgres in compose |
| `REDIS_URL` | _(empty = disabled)_ | cache |
| `OPA_URL` | _(empty = local mirror)_ | e.g. `http://opa:8181` |
| `OPA_BUNDLE_DIR` | `./deploy/opa/store` | Rego + data.json source |
| `LLM_PROVIDER` | _(empty = deterministic)_ | `foundry` \| `openai` |
| `GITHUB_TOKEN` | _(empty)_ | publish + check polling |
| `ALLOWED_GIT_HOSTS` | `github.com` | clone allow-list |
| `ALLOW_LOCAL_REPOS` | `false` | local-path repos (dev/tests only) |
| `SANDBOX_MODE` | `local` | `local` \| `docker` |
| `COSIGN_KEY_REF` | _(empty = step skipped)_ | signing key |
| `CHAINLOOP_*` | _(empty = step skipped)_ | attestation credentials |
| `MAX_REPAIR_ATTEMPTS` | `3` | repair loop bound |
