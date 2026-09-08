# Tool + capability allow-listing (PDF §3 "fail closed", §15 hallucinations).
# Every tool in the plan must exist in the approved catalog and must not
# have been prohibited by the requester. Mirrored by the Python local
# evaluator in backend/src/ci_agent/policy/local.py — keep them in sync.
package ciagent.policy

deny[{"rule": "TOOL_NOT_APPROVED", "message": msg}] {
	some i
	tool := input.plan.tools[i].name
	not tool_approved(tool)
	msg := sprintf("tool '%s' is not in the approved catalog", [tool])
}

deny[{"rule": "TOOL_PROHIBITED", "message": msg}] {
	some i
	tool := input.plan.tools[i].name
	input.intent.prohibited_tools[_] == tool
	msg := sprintf("tool '%s' was explicitly prohibited by the request", [tool])
}

deny[{"rule": "CAPABILITY_NOT_APPROVED", "message": msg}] {
	input.intent.capabilities[_] == cap
	not capability_approved(cap)
	msg := sprintf("capability '%s' is not approved for automated CI generation", [cap])
}

# Unknown / floating tool versions need a human (supply-chain, §15).
approval_reasons[{"rule": "TOOL_VERSION_UNKNOWN", "message": msg}] {
	some i
	tool_name := input.plan.tools[i].name
	version_unknown(input.plan.tools[i].version)
	msg := sprintf("tool '%s' has no pinned version", [tool_name])
}

tool_approved(name) {
	data.approved.tools[_] == name
}

capability_approved(cap) {
	data.approved.capabilities[_] == cap
}

version_unknown(v) {
	v == ""
}

version_unknown(v) {
	v == "latest"
}

version_unknown(v) {
	v == "unknown"
}
