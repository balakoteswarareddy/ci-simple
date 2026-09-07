# ADR 0001 — Modular monolith, not microservices

- Status: accepted
- Date: 2026-09-07
- Context: PDF §4

## Decision

Ship one API process with strict module boundaries (`backend/src/ci_agent/*`),
one UI build, and backing services (Postgres, Redis, OPA) over the network —
instead of per-phase microservices.

## Rationale

A run's lifecycle (discover → plan → policy → render → validate → publish) is
a single state machine with shared transactions (run row + events + evidence).
Splitting it across services would trade compile-time imports for runtime
contracts, retries, and distributed tracing — with zero scaling need (runs are
I/O-bound minutes-long jobs; horizontal scale = more API replicas behind the
DB). Module contracts (`docs/ARCHITECTURE.md` §3) give the team the same
ownership boundaries without the ops tax.

## Consequences

- `docker-compose.yml` stays small (db, redis, opa, api, ui, prometheus-opt).
- Extraction path preserved: `policy` already speaks HTTP to OPA; `knowledge`
  and `evidence` have store interfaces that could move behind services later.
