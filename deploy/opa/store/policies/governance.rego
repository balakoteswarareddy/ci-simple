# Human-approval triggers (PDF §3 "human approval for high-risk changes",
# §16 "human approval before commit/PR"). These pause the run before any
# mutation; generation + validation artifacts stay reviewable while paused.
package ciagent.policy

# Publishing CI/security changes to a protected branch always needs a human.
approval_reasons[{"rule": "PROTECTED_BRANCH", "message": msg}] {
	data.limits.protected_branches[_] == input.intent.target_branch
	input.intent.publish
	msg := sprintf("publishing to protected branch '%s'", [input.intent.target_branch])
}

approval_reasons[{"rule": "PRODUCTION_DEPLOY", "message": "plan includes a production deployment job"}] {
	input.plan.has_deploy_job
	input.intent.deployment_target == "production"
}

approval_reasons[{"rule": "SECURITY_REMOVAL", "message": "plan removes or weakens a security control"}] {
	input.plan.removes_security
}

approval_reasons[{"rule": "CLOUD_OIDC", "message": msg}] {
	input.plan.cloud_oidc
	msg := "plan requests cloud credentials via OIDC — verify the trust policy"
}

approval_reasons[{"rule": "HIGH_RISK", "message": "run classified as high risk"}] {
	input.risk.level == "high"
}

approval_reasons[{"rule": "FORK_CONTEXT", "message": "change comes from a fork — review secrets usage"}] {
	input.repo.is_fork
}
