# GitHub Action allow-listing + pinning (PDF §15 supply-chain compromise).
# Actions match by "owner/name@" prefix so versions stay flexible while the
# identity is controlled. Pinning to an immutable ref is mandatory.
package ciagent.policy

deny[{"rule": "ACTION_NOT_PINNED", "message": msg}] {
	some i
	a := input.plan.actions[i]
	not a.pinned
	not data.limits.allow_unpinned
	msg := sprintf("action '%s' is not pinned to an immutable version", [a.uses])
}

deny[{"rule": "ACTION_NOT_APPROVED", "message": msg}] {
	some i
	uses := input.plan.actions[i].uses
	not action_approved(uses)
	msg := sprintf("action '%s' is not in the approved action list", [uses])
}

action_approved(uses) {
	some j
	prefix := data.approved.actions[j]
	startswith(uses, prefix)
}
