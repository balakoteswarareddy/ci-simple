# ADR 0003 — Versioned Pipeline IR between plan and renderers

- Status: accepted
- Date: 2026-09-07
- Context: PDF §6 pipeline model

## Decision

The planner outputs a tool plan; `pipeline/ir.py` lowers it to a versioned,
pydantic-validated Intermediate Representation (jobs/steps/permissions); four
renderers (GitHub, Azure, GitLab, Jenkins) consume only the IR.

## Rationale

Without the IR, every policy/validation feature would need N platform
implementations, and platform drift would be invisible. The IR gives one schema
to validate, one golden file per platform to byte-compare, and makes a fifth
platform a pure function from IR → text.

## Consequences

- Renderers are deterministic and LLM-free; golden tests pin every byte.
- IR changes are versioned; old evidence bundles remain interpretable.
