# ADR 0002 — OPA as the policy decision point, with a local mirror

- Status: accepted
- Date: 2026-09-07
- Context: PDF §5 governance

## Decision

All verdicts come from Rego evaluated by an OPA server (`deploy/opa/store`).
A minimal Python mirror (`policy/local.py`) exists solely for dev/tests when
`OPA_URL` is unset, and every response + `/readyz` names the evaluator.

## Rationale

Policy must be reviewable (Rego + `opa test`), hot-reloadable without code
deploys, and testable in CI against a live server. The mirror keeps the inner
loop (`make api-dev`, unit tests) dependency-free — but it is deliberately
audited: it can only express the same verdicts, it warns loudly, and prod
compose always sets `OPA_URL`.

## Consequences

- Any evaluator error fails closed to DENY (`policy/engine.py`).
- The mirror must be kept in sync with Rego verdicts; the OPA-parity
  integration test (live server, skips without binary) guards drift.
