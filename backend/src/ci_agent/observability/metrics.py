"""Prometheus metrics (PDF §10 observability).

Latency, token usage/cost, tool calls, policy denials, validation errors,
refinement attempts, approval wait time, generation success rate.
"""
from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry()

RUNS_TOTAL = Counter(
    "ciagent_runs_total", "Runs started by platform and final status",
    ["platform", "status"], registry=REGISTRY,
)
RUN_DURATION = Histogram(
    "ciagent_run_duration_seconds", "End-to-end run duration by platform",
    ["platform"], registry=REGISTRY,
)
RUN_STEP_DURATION = Histogram(
    "ciagent_run_step_duration_seconds", "Per-step duration",
    ["step"], registry=REGISTRY,
)
POLICY_DECISIONS = Counter(
    "ciagent_policy_decisions_total", "Policy decisions by outcome and evaluator",
    ["decision", "evaluator"], registry=REGISTRY,
)
VALIDATION_FINDINGS = Counter(
    "ciagent_validation_findings_total", "Validation findings by validator and level",
    ["validator", "level"], registry=REGISTRY,
)
LLM_TOKENS = Counter(
    "ciagent_llm_tokens_total", "LLM token usage by model and direction",
    ["model", "direction"], registry=REGISTRY,
)
LLM_COST = Counter(
    "ciagent_llm_cost_usd_total", "Estimated LLM spend by model",
    ["model"], registry=REGISTRY,
)
TOOL_CALLS = Counter(
    "ciagent_tool_calls_total", "External tool/CLI invocations by tool and status",
    ["tool", "status"], registry=REGISTRY,
)
REPAIR_ATTEMPTS = Counter(
    "ciagent_repair_attempts_total", "Bounded repair loop iterations by outcome",
    ["outcome"], registry=REGISTRY,
)
APPROVAL_WAIT = Histogram(
    "ciagent_approval_wait_seconds", "Time runs spend awaiting approval",
    registry=REGISTRY,
)
KNOWLEDGE_RECORDS = Gauge(
    "ciagent_knowledge_records", "Knowledge records in the store",
    registry=REGISTRY,
)
RUNS_IN_PROGRESS = Gauge(
    "ciagent_runs_in_progress", "Runs currently executing",
    registry=REGISTRY,
)


def metrics_response() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
