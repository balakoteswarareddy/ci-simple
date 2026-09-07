# Least-privilege permission policy (PDF §10 GitHub permissions, §15).
# Read-only plans pass. Any `write` scope needs human review, a small set of
# scopes is never granted, and unknown scopes are rejected (fail closed).
# `id-token: write` (OIDC) is allowed through review, never denied outright.
package ciagent.policy

approval_reasons[{"rule": "PERMISSION_WRITE_REVIEW", "message": msg}] {
	some k
	input.plan.permissions[k] == "write"
	msg := sprintf("permission '%s: write' requires review", [k])
}

deny[{"rule": "PERMISSION_NEVER_WRITE", "message": msg}] {
	some k
	input.plan.permissions[k] == "write"
	data.limits.never_write[_] == k
	msg := sprintf("permission '%s: write' is never granted by generated workflows", [k])
}

deny[{"rule": "PERMISSION_UNKNOWN", "message": msg}] {
	some k
	input.plan.permissions[k]
	not permission_known(k)
	msg := sprintf("unknown permission scope '%s'", [k])
}

permission_known(k) {
	data.limits.known_permissions[_] == k
}
