# ADR 0007 — UI uses hash routing + fetch, no framework lock-in

- Status: accepted
- Date: 2026-09-07
- Context: PDF Phase 7 surfaces

## Decision

The React UI uses hash routing (`#/runs/<id>`) and a hand-written `fetch`
client (`ui/src/api.ts`) with zero runtime dependencies beyond React.

## Rationale

The UI is served as static files (nginx) and as a Vite dev app behind a proxy;
hash routing works identically under both with no server rewrite rules. A thin
typed client keeps the `/api/v1` contract explicit and reviewable, avoids
client-state framework churn, and keeps the production bundle dependency-free.

## Consequences

- Deep links look like `/app/#/runs/<id>` — acceptable for an internal tool.
- API contract changes must update `ui/src/types.ts` + `ui/src/api.ts` by
  hand; the build (`tsc --noEmit`) fails on drift.
