# ADR 0004 — Deterministic-first planner, LLM as validated enrichment

- Status: accepted
- Date: 2026-09-07
- Context: PDF §7 agent design

## Decision

Intent parsing and tool selection run deterministically; the LLM
(`llm/foundry.py`, OpenAI-compatible path) may only enrich within
`llm/schemas.py`, and its output is validated before use. With no provider
configured the system is fully functional (`deterministic-fallback`).

## Rationale

CI generation must be reproducible (golden tests), auditable (evidence must
explain *why* a tool was chosen), and safe against prompt injection. A
generate-then-validate loop with an LLM in the critical path would break all
three. The LLM earns its place on prose (explanations, intent enrichment),
never on decisions.

## Consequences

- Evals (`backend/tests/evals/`) test parser behavior, not model vibes.
- `LLM_PROVIDER` empty is a supported production configuration.
