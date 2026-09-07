# Local services — whole configuration

This repo ships its local workspace services as **runnable files** (this is the
index; the files themselves are authoritative) **and** documents every knob
here, as requested. One command starts the full stack:

```bash
docker compose up --build -d        # or: make dev-up
docker compose --profile monitoring up --build -d   # + Prometheus
```

## Service map

| Service | Image / build | Ports (host) | Role |
|---|---|---|---|
| `db` | `postgres:16-alpine` | _(internal)_ | evidence + runs database |
| `redis` | `redis:7-alpine` | _(internal)_ | cache |
| `opa` | `openpolicyagent/opa:1.0.0` | `8181` | policy decisions (Rego) |
| `api` | `./backend/Dockerfile` | `8000` | FastAPI: orchestrator + REST |
| `ui` | `./ui/Dockerfile` | `8080` | React SPA behind nginx |
| `prometheus` | `prom/prometheus:v2.53.0` | `9090` (profile `monitoring`) | metrics (scrapes api:8000/metrics) |

Networks: `backend` (db, redis, opa, api, prometheus), `frontend` (api, ui).
Volumes: `pgdata`, `redisdata`, `agent-work`, `agent-data`, `promdata`.

Runnable files:

- `docker-compose.yml` — the whole stack (below, verbatim).
- `backend/Dockerfile` — API image incl. pinned OSS CLIs
  (actionlint v1.7.7, syft v1.21.0, cosign v2.4.3).
- `ui/Dockerfile` + `ui/nginx.conf` — SPA build + same-origin `/api` proxy.
- `deploy/opa/config.yaml` — OPA server config (below, verbatim).
- `deploy/opa/store/` — Rego policies + `data.json` catalog (mounted read-only
  into **both** `opa` at `/store` and `api` at `/opt/ci-agent/policy-store`).
- `deploy/prometheus/prometheus.yml` — scrape config (below, verbatim).
- `config/agent.yaml.example` — optional static agent config; env vars win.
- `examples/jenkins/docker-compose.yml` — ephemeral Jenkins harness (replay
  generated Jenkinsfiles; see `docs/JENKINS_TESTING.md`).

## 1. `docker-compose.yml` (verbatim)

```yaml
name: ci-agent

services:
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-ciagent}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-ciagent-dev-pw}
      POSTGRES_DB: ${POSTGRES_DB:-ciagent}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-ciagent} -d ${POSTGRES_DB:-ciagent}"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 10s
    networks:
      - backend

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 5s
    networks:
      - backend

  opa:
    image: openpolicyagent/opa:1.0.0
    restart: unless-stopped
    # NOTE: no container healthcheck — the OPA image is a bare static binary
    # (no shell/curl). The API retries OPA at startup and /readyz reports it.
    command:
      - run
      - --server
      - --addr=0.0.0.0:8181
      - --config-file=/config/opa-config.yaml
      - /store
    volumes:
      - ./deploy/opa/store:/store:ro
      - ./deploy/opa/config.yaml:/config/opa-config.yaml:ro
    ports:
      - "8181:8181"
    networks:
      - backend

  api:
    build: ./backend
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
      opa:
        condition: service_started
    environment:
      CI_AGENT_ENV: ${CI_AGENT_ENV:-dev}
      CI_AGENT_DATA_DIR: /var/lib/ci-agent/data
      CI_AGENT_API_KEY: ${CI_AGENT_API_KEY:-}
      DATABASE_URL: postgresql+psycopg2://${POSTGRES_USER:-ciagent}:${POSTGRES_PASSWORD:-ciagent-dev-pw}@db:5432/${POSTGRES_DB:-ciagent}
      REDIS_URL: redis://redis:6379/0
      OPA_URL: http://opa:8181
      OPA_BUNDLE_DIR: /opt/ci-agent/policy-store
      LLM_PROVIDER: ${LLM_PROVIDER:-}
      FOUNDRY_ENDPOINT: ${FOUNDRY_ENDPOINT:-}
      FOUNDRY_API_KEY: ${FOUNDRY_API_KEY:-}
      FOUNDRY_DEPLOYMENT: ${FOUNDRY_DEPLOYMENT:-gpt-4o-mini}
      FOUNDRY_API_VERSION: ${FOUNDRY_API_VERSION:-2024-10-21}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      OPENAI_MODEL: ${OPENAI_MODEL:-gpt-4o-mini}
      GITHUB_TOKEN: ${GITHUB_TOKEN:-}
      ALLOWED_GIT_HOSTS: ${ALLOWED_GIT_HOSTS:-github.com}
      SANDBOX_MODE: ${SANDBOX_MODE:-local}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      LOG_FORMAT: ${LOG_FORMAT:-json}
    volumes:
      - agent-work:/var/lib/ci-agent/work
      - agent-data:/var/lib/ci-agent/data
      - ./deploy/opa/store:/opt/ci-agent/policy-store:ro
    ports:
      - "8000:8000"
    networks:
      - backend
      - frontend

  ui:
    build: ./ui
    restart: unless-stopped
    depends_on:
      - api
    ports:
      - "8080:80"
    networks:
      - frontend

  prometheus:
    image: prom/prometheus:v2.53.0
    profiles: ["monitoring"]
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.path=/prometheus
    volumes:
      - ./deploy/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - promdata:/prometheus
    ports:
      - "9090:9090"
    networks:
      - backend

networks:
  backend:
  frontend:

volumes:
  pgdata:
  redisdata:
  agent-work:
  agent-data:
  promdata:
```

## 2. OPA (`opa` + `deploy/opa/`)

OPA runs as a server (`opa run --server --addr=0.0.0.0:8181
--config-file=/config/opa-config.yaml /store`) with the bundle directory
mounted read-only. The API queries
`POST http://opa:8181/v1/data/ciagent/policy/decision` and fails closed to
DENY on any error.

`deploy/opa/config.yaml` (verbatim):

```yaml
services:
  acmecorp:
    url: https://example.com/control-plane
    # Placeholder: wire your real control plane here for bundle/status APIs.
    # The local ./store directory is authoritative until then.

decision_logs:
  console: true
  drop_decision: "data.ciagent.policy.drop_decision"

status:
  console: true

server:
  decision_logs:
    console: true
```

`deploy/opa/store/` contents: `data.json` (top-level `approved`, `denied`,
`limits` — merged by OPA at the data root, see `docs/POLICY.md` for why it
must stay one file) and `policies/*.rego` (`main`, `tools`, `actions`,
`permissions`, `licenses`, `governance`) plus `main_test.rego`.
Change flow: edit → `opa check` + `opa test` → `docker compose up -d opa api`
→ confirm `/readyz` shows `opa.ok` with data loaded.

Health probes:

```bash
curl localhost:8181/health?bundle=true      # server alive
curl localhost:8181/v1/data/approved/tools  # data mount present (31 tools)
```

## 3. API (`api`)

Built from `backend/Dockerfile`: `python:3.11-slim`, non-root `ciagent`
(uid 10001), pinned OSS CLIs baked in (actionlint v1.7.7, syft v1.21.0,
cosign v2.4.3 — each with a latest-release fallback so a yanked pin can't
break the build), uvicorn on `:8000`, container healthcheck on `/healthz`.
Waits for healthy `db` + `redis`; starts once `opa` has started (and retries
it — see the compose comment about the missing OPA healthcheck).

Every setting is env-driven; the authoritative list with defaults is
`backend/src/ci_agent/config.py`, the curated table is in `docs/API.md`.
Compose overrides worth knowing:

- `DATABASE_URL` → postgres via psycopg2 (SQLite only for `make api-dev`).
- `REDIS_URL=redis://redis:6379/0` (safe to unset — caching disables itself).
- `OPA_URL=http://opa:8181` (unset ⇒ local-mirror mode, dev only).
- `OPA_BUNDLE_DIR=/opt/ci-agent/policy-store` — the same store OPA serves,
  so planner catalog and enforced policy can't drift.
- Secrets (`CI_AGENT_API_KEY`, `GITHUB_TOKEN`, `FOUNDRY_API_KEY`,
  `OPENAI_API_KEY`) arrive as env vars, never files; rotation = new env +
  `docker compose up -d api` (see `docs/RUNBOOKS.md` §6).

## 4. UI (`ui`)

`ui/Dockerfile` builds the React SPA (`npm run build`) and serves `dist/`
from nginx (`ui/nginx.conf`): same-origin `/api/` → `api:8000` (300 s
timeouts for long polls), `/healthz` proxied, hashed `/assets/` cached
immutably, SPA fallback to `index.html`. No env needed at runtime; the API
key field in the sidebar is stored in the browser's localStorage.

## 5. Postgres (`db`)

`postgres:16-alpine`, data in `pgdata`, gated by a `pg_isready` healthcheck
that the API depends on. Schema auto-created at startup (`common/db.py`).
Connect: `docker compose exec db psql -U ciagent ciagent`. Backup:
`docker compose exec db pg_dump -U ciagent ciagent > backup.sql`.

## 6. Redis (`redis`)

`redis:7-alpine` with AOF persistence (`redisdata`). No auth in dev; for
shared environments set `REDIS_URL` with a password and add
`--requirepass` to the command. The API treats Redis as a cache — safe to
flush or remove.

## 7. Prometheus (`prometheus`, profile `monitoring`)

`prom/prometheus:v2.53.0`, storage in `promdata`, UI on `:9090`.
`deploy/prometheus/prometheus.yml` (verbatim):

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: ci-agent-api
    static_configs:
      - targets: ["api:8000"]
    metrics_path: /metrics
    scrape_interval: 15s

  - job_name: prometheus
    static_configs:
      - targets: ["localhost:9090"]
```

Verify: `curl localhost:8000/metrics | grep ciagent_` (run counters,
durations, policy verdicts), then check the `ci-agent-api` target is UP at
`http://localhost:9090/targets`.

## 8. Jenkins harness (`examples/jenkins/`, separate stack)

Ephemeral controller (`jenkins/jenkins:2.516.1-lts-jdk21` on `:8080`,
admin/admin, setup wizard skipped) + `replay.sh` for one-shot replays of
generated Jenkinsfiles into timestamped scratch jobs. Own compose project
(`ci-agent-jenkins-harness`), own volume, `docker compose down -v` wipes it.
Full flow in `docs/JENKINS_TESTING.md`.

## 9. Day-to-day commands

```bash
make dev-up / dev-down / dev-logs   # stack lifecycle
make api-dev / ui-dev               # dependency-free local dev (SQLite, no docker)
make compose-check                  # validate compose YAML without docker
make opa-check                      # opa check ./deploy/opa/store
curl localhost:8000/readyz | jq     # database + opa(+data) + knowledge + llm
curl localhost:8000/healthz         # liveness
```

## 10. Ports cheat-sheet

| Port | Service | Endpoint |
|---|---|---|
| 8000 | api | `/docs`, `/api/v1/*`, `/healthz`, `/readyz`, `/metrics` |
| 8080 | ui | SPA |
| 8181 | opa | `/health`, `/v1/data/*` |
| 9090 | prometheus | UI + `/targets` (monitoring profile) |
