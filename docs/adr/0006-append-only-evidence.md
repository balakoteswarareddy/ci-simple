# ADR 0006 — Append-only evidence, immutable approvals

- Status: accepted
- Date: 2026-09-07
- Context: PDF §8 audit

## Decision

Run history is an append-only JSONL event log plus immutable per-run evidence
bundles (`evidence/store.py`); approvals are insert-only rows; there is no API
to edit or delete audit data.

## Rationale

A CI-generating agent with publish rights is a privileged actor; its audit
trail must be tamper-evident by construction, not by convention. Append-only
storage makes "who approved what, with which policy verdict, over which YAML"
answerable forever, and makes the absence of a delete endpoint a feature.

## Consequences

- No `DELETE` routes; retention is an ops concern (volume lifecycle), not an
  API concern.
- Evidence bundles are content-addressed and served verbatim at
  `GET /runs/{id}/evidence`.
