# CI Agent policy decision point (PDF: §6 step 6, Phase 2 governance).
#
# Query: POST /v1/data/ciagent/policy/decision   {"input": {...}}
#
# Input contract (see docs/POLICY.md for the JSON schema):
#   input.intent  = {platform, capabilities[], prohibited_tools[],
#                    target_branch, deployment_target, publish}
#   input.plan    = {tools[{name,version,capability}], actions[{uses,pinned}],
#                    permissions{}, licenses[], has_deploy_job,
#                    touches_security, removes_security, cloud_oidc}
#   input.repo    = {default_branch, is_fork}
#   input.risk    = {level}
#
# Decision semantics: DENY fails the run (fail closed). APPROVAL_REQUIRED
# pauses the run before any mutation (commit/PR). ALLOW proceeds.
package ciagent.policy

default allow = false

# --- Final decision: exactly one of the three rules below is true. ---

decision = {"decision": "DENY", "deny": deny, "approval_reasons": approval_reasons} {
	count(deny) > 0
}

decision = {"decision": "APPROVAL_REQUIRED", "deny": deny, "approval_reasons": approval_reasons} {
	count(deny) == 0
	approval_required
}

decision = {"decision": "ALLOW", "deny": deny, "approval_reasons": approval_reasons} {
	count(deny) == 0
	not approval_required
}

allow {
	count(deny) == 0
	not approval_required
}

approval_required {
	count(approval_reasons) > 0
}

# --- Fail closed on malformed input: missing sections stop the run. ---

deny[{"rule": "PLAN_MALFORMED", "message": "input.plan.tools is missing"}] {
	not input.plan.tools
}

deny[{"rule": "PLAN_MALFORMED", "message": "input.plan.permissions is missing"}] {
	not input.plan.permissions
}

deny[{"rule": "INTENT_MALFORMED", "message": "input.intent.capabilities is missing"}] {
	not input.intent.capabilities
}

# Never drop decision logs (referenced by opa-config.yaml).
drop_decision = false
