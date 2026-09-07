# Threat model

Scope: the CI agent as deployed via `docker-compose.yml` (or equivalent):
UI → API → OPA/Postgres/Redis, plus outbound GitHub, LLM, and knowledge-source
traffic. Out of scope: the security of user repos themselves (the agent scans
but does not vouch for them).

## Assets

1. `GITHUB_TOKEN` / LLM keys / Cosign keys (high value, broad blast radius).
2. Evidence store + database (audit integrity — must be append-only in spirit).
3. Generated workflows landing in customer repos (supply-chain injection target).
4. OPA bundle (policy integrity — a quiet edit could allow everything).

## Abuse cases and mitigations

| # | Abuse case | Mitigation (code) |
|---|---|---|
| 1 | Prompt injection in repo files/request tricks the planner into adding malicious steps | Planner is deterministic-first; LLM output is schema-validated (`llm/schemas.py`) and can only select catalog tools; policy re-checks the final plan |
| 2 | Malicious action version (tag moved) | Actions tag-pinned at render, SHA-hardened by `pin_actions.py`; OPA requires known prefixes + pinned refs |
| 3 | Exfiltration via generated workflow (`curl` secrets to attacker) | `validation/security_checks.py` blocks suspicious run-content; OPA denies unknown tools; HIGH-risk plans need approval |
| 4 | SSRF via `repo_url` (clone internal hosts) | `ALLOWED_GIT_HOSTS` allow-list; local paths need `ALLOW_LOCAL_REPOS=true` |
| 5 | SSRF via knowledge ingest URL | `KNOWLEDGE_ALLOW_HOSTS` allow-list, HTTPS-only, fetch timeout, claim verification |
| 6 | Secret leak into logs/evidence/UI | `security/redact.py` on all logging paths; secrets never stored (see `security/secrets.py` + `security/auth.py`) |
| 7 | Silent policy bypass (OPA down / bundle bad) | Fail-closed DENY on any evaluator error; `data_present()` mount guard; CI live-decision test |
| 8 | Unauthorized approvals | `X-API-Key` auth when configured; actor recorded; decisions immutable once written |
| 9 | Tampered evidence (rewrite history) | Append-only JSONL + content-addressed bundles; DB rows never updated in place for audit fields |
| 10 | Runaway sandbox commands | `execution/sandbox.py`: no network, timeouts, command allow-list in docker mode |
| 11 | Dependency confusion in generated `pip install` | Planner pins versions from knowledge; OPA `licenses.rego` denies bad licenses |
| 12 | Fork PR exfiltrating secrets on publish | `governance.rego` denies publish from forks; protected-branch push denied |

## Residual risks (accepted, documented)

- The deterministic planner's capability parser can misread adversarial prose;
  the policy gate + human approval on HIGH risk is the backstop, not perfect
  NLP.
- Local-mirror policy mode is honest but weaker than OPA (no Rego updates at
  runtime); compose/prod always wires `OPA_URL`, and `/readyz` exposes the mode.
- SBOM/sign/attest steps are skipped without credentials — visible via
  provenance, but a misconfigured prod could run unsigned; the runbook
  (RUNBOOKS.md) makes the preflight check explicit.
