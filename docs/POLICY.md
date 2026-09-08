# Policy governance (OPA)

OPA is the system's policy decision point. Every run's plan is evaluated before
anything is rendered, committed, or published. The local evaluator
(`backend/src/ci_agent/policy/local.py`) is a deliberately narrow mirror used
only when `OPA_URL` is unset (dev/tests); production composes the real OPA
server (`docker-compose.yml`, `opa` service).

## Layout

```
deploy/opa/
  config.yaml          # server config (service/listening; bundle store)
  store/               # mounted read-only into OPA at /store AND into the API
    data.json          # catalog data -> data.approved / data.denied / data.limits
    policies/
      main.rego        # decision entry: ciagent.policy.decision
      tools.rego       # tool allow-list / deny-list
      actions.rego     # action prefixes, pinning, SHA hardening
      permissions.rego # known permission keys, least-privilege checks
      licenses.rego    # denied license list
      governance.rego  # branch protection, forks, publish gating
      main_test.rego   # `opa test` suite for the bundle
```

## Why a single `data.json` (read before splitting)

OPA merges every `*.json` file found at the store root **into the data root**.
A file named `approved.json` containing `{"tools": [...]}` would therefore be
served as `data.tools` — not `data.approved.tools` — and every `data.approved`
reference in Rego would be silently undefined. The single `data.json` with
top-level `approved`, `denied`, and `limits` keys maps exactly onto
`data.approved.*`, `data.denied.*`, `data.limits.*`. CI guards this: the
`policy-live-decision` job starts OPA from `./deploy/opa/store`, queries
`data.approved.tools`, and asserts a live ALLOW verdict.

## Decision contract

Input (`policy/engine.py` builds this; also accepted by
`POST /api/v1/policies/evaluate`):

```jsonc
{
  "intent":   { "platform": "github", "capabilities": ["lint"], "prohibited_tools": [],
                "target_branch": "feature/x", "deployment_target": "", "publish": false },
  "plan":     { "tools": [{ "name": "ruff", "version": "0.4.0", "capability": "lint" }],
                "actions": [{ "uses": "actions/checkout@v4", "pinned": true }],
                "permissions": { "contents": "read" }, "licenses": ["MIT"],
                "has_deploy_job": false, "touches_security": false,
                "removes_security": false, "cloud_oidc": false },
  "repo":     { "repo_url": "https://github.com/o/r", "default_branch": "main", "is_fork": false },
  "risk_level": "low", "target_branch": "feature/x", "publish": false
}
```

Output: `{ decision, deny[], approval_reasons[], evaluator }` where decision is
`ALLOW` | `ALLOW_WITH_APPROVAL` | `DENY`.

- **DENY** on: unknown/denied tool, unpinned or unknown action, unknown
  permission, denied license, push to a protected branch, publish from a fork,
  `removes_security`, evaluator error (fail closed).
- **ALLOW_WITH_APPROVAL** on: deploy job, cloud OIDC, elevated permissions,
  HIGH risk, publish runs — the run pauses at `awaiting_approval`.
- Otherwise **ALLOW**.

## Evaluator selection

`policy/engine.py`: if `OPA_URL` is set → query `POST {OPA_URL}/v1/data/<POLICY_DECISION_PATH>`
(`ciagent/policy/decision` by default) with a timeout; on any error → DENY.
If unset → local mirror + loud warning (and `/readyz` reports
`mode: local-mirror`). `policy/opa.py::data_present()` additionally GETs
`/v1/data/approved/tools` at startup so a bad mount can never pass silently.

## Changing policy safely

1. Edit Rego or `data.json` in `deploy/opa/store/`.
2. `make opa-check` (or `opa check ./deploy/opa/store`) and
   `opa test ./deploy/opa/store -v`.
3. `POST /api/v1/policies/evaluate` with the sample payload (see Policies page)
   to confirm the verdict you expect.
4. Restart (or wait for) the OPA container; confirm `/readyz` shows
   `opa.ok: true` with `data_loaded: true`, then merge.

`backend/src/ci_agent/policy/catalog.py` exposes the same `data.json` to the
planner, so the allow-lists the planner plans against and the policy OPA
enforces can never drift: one file, two readers.
