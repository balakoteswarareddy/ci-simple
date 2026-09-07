# Runbooks

## 1. First boot (local, full stack)

```bash
cp config/agent.yaml.example config/agent.yaml   # optional file config
docker compose up --build -d                     # or: make dev-up
curl localhost:8000/readyz | jq                  # all checks true?
```

Expected: `database.ok`, `opa.ok` (+ `data_loaded`), `knowledge.ok`
(31 records), `llm.ok` (`deterministic-fallback` until a provider is set).
UI at `http://localhost:8080`, API docs at `http://localhost:8000/docs`.

Minimal boot without docker: `make api-dev` (SQLite + local policy) and
`make ui-dev` in a second terminal.

## 2. Preflight before trusting a run in prod

1. `/readyz`: `opa.mode` must be `server` (never `local-mirror`), knowledge
   `fresh_records > 0`.
2. Secrets present: `GITHUB_TOKEN` (publish), `COSIGN_KEY_REF` (sign),
   `CHAINLOOP_*` (attest) — else those steps skip with provenance.
3. `opa check ./deploy/opa/store && opa test ./deploy/opa/store -v` green.
4. Action refs hardened: `python backend/scripts/pin_actions.py --check`.

## 3. OPA is failing / `/readyz` shows `opa.ok: false`

1. `docker compose logs opa` — bundle load errors name the file/line.
2. Verify the mount: `curl localhost:8181/v1/data/approved/tools | jq length`
   must be 31. Empty/404 → the `./deploy/opa/store` volume didn't mount or
   `data.json` lost its top-level keys (see `docs/POLICY.md`).
3. Query the decision directly:
   `curl localhost:8181/v1/data/ciagent/policy/decision -d @payload.json`.
4. Runs fail closed (DENY) while OPA is unhealthy — fix OPA, no run cleanup
   needed; re-submit denied runs.

## 4. A run is stuck in `running`

1. `GET /runs/{id}/events` — the last event names the step.
2. `docker compose logs api | grep <run-id>` for tracebacks.
3. Common causes: clone timeout (private repo without token / wrong host —
   check `ALLOWED_GIT_HOSTS`), LLM timeout (falls back automatically; check
   `FOUNDRY_*`), scanner binary hanging (sandbox timeout kills at
   `SANDBOX_TIMEOUT_SECONDS`, records `skipped`).
4. The orchestrator has no resume: cancel (`DELETE` is intentionally absent —
   auditability) by letting it finish, then re-submit.

## 5. A run is `awaiting_approval` — what to check before approving

1. Run detail → Plan tab: tools all known? versions pinned? permissions minimal?
2. Policy tab: which `approval_reasons` fired? (deploy job, OIDC, elevated
   perms, publish?)
3. Workflow tab: read the YAML; Workflow-security validator must be PASS.
4. Approve with a reason (`POST /runs/{id}/approve` or UI) — recorded forever.

## 6. Rotating secrets

`CI_AGENT_API_KEY`, `GITHUB_TOKEN`, `FOUNDRY_API_KEY`, `OPENAI_API_KEY`,
`POSTGRES_PASSWORD` are env-only (never in files): update the environment,
`docker compose up -d api` (and `db` for the postgres password — note the
password is read by the `db` image only on first volume init; to rotate an
existing volume, change it inside postgres and update the API env to match).

## 7. Backups

- Postgres: standard `pg_dump` of the `ciagent` DB (runs/events/approvals).
- `agent-data` volume (`CI_AGENT_DATA_DIR`): evidence JSONL + bundles.
- `AGENT_WORK_DIR` clones are ephemeral — exclude from backups.

## 8. Upgrading the OPA bundle / tool catalog

1. Edit `deploy/opa/store/{policies/*.rego,data.json}`.
2. `opa check`, `opa test`, `POST /policies/evaluate` sample payload.
3. `docker compose up -d opa api` (both mount the store read-only).
4. Confirm `/readyz` + catalog version, then announce: policy changes apply to
   new runs immediately; in-flight runs keep their original verdict.
