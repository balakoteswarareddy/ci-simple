# OPA unit tests for the CI Agent bundle. Run: opa test ./deploy/opa/store
package ciagent.policy

clean_input = {"intent": {"platform": "github", "capabilities": ["lint", "test"], "prohibited_tools": [], "target_branch": "feature/ci", "deployment_target": "", "publish": false}, "plan": {"tools": [{"name": "ruff", "version": "0.4.0", "capability": "lint"}, {"name": "pytest", "version": "8.0.0", "capability": "test"}], "actions": [{"uses": "actions/checkout@v4", "pinned": true}], "permissions": {"contents": "read"}, "licenses": ["MIT"], "has_deploy_job": false, "touches_security": false, "removes_security": false, "cloud_oidc": false}, "repo": {"default_branch": "main", "is_fork": false}, "risk": {"level": "low"}}

test_allow_clean_plan {
	decision.decision == "ALLOW" with input as clean_input
}

test_deny_unapproved_tool {
	d := decision with input as object.union(clean_input, {"plan": object.union(clean_input.plan, {"tools": [{"name": "evil-linter", "version": "1.0.0", "capability": "lint"}]})})
	d.decision == "DENY"
	count(d.deny) == 1
}

test_deny_prohibited_tool {
	modified := object.union(clean_input, {"intent": object.union(clean_input.intent, {"prohibited_tools": ["ruff"]})})
	d := decision with input as modified
	d.decision == "DENY"
}

test_deny_unpinned_action {
	modified := object.union(clean_input, {"plan": object.union(clean_input.plan, {"actions": [{"uses": "actions/checkout@main", "pinned": false}]})})
	d := decision with input as modified
	d.decision == "DENY"
}

test_deny_unknown_permission {
	modified := object.union(clean_input, {"plan": object.union(clean_input.plan, {"permissions": {"contents": "read", "root-access": "write"}})})
	d := decision with input as modified
	d.decision == "DENY"
}

test_approval_protected_branch_publish {
	modified := object.union(clean_input, {"intent": object.union(clean_input.intent, {"target_branch": "main", "publish": true})})
	d := decision with input as modified
	d.decision == "APPROVAL_REQUIRED"
}

test_no_approval_when_generate_only {
	modified := object.union(clean_input, {"intent": object.union(clean_input.intent, {"target_branch": "main", "publish": false})})
	d := decision with input as modified
	d.decision == "ALLOW"
}

test_approval_write_permission {
	modified := object.union(clean_input, {"plan": object.union(clean_input.plan, {"permissions": {"contents": "write"}})})
	d := decision with input as modified
	d.decision == "APPROVAL_REQUIRED"
}

test_deny_denied_license {
	modified := object.union(clean_input, {"plan": object.union(clean_input.plan, {"licenses": ["MIT", "AGPL-3.0-only"]})})
	d := decision with input as modified
	d.decision == "DENY"
}

test_deny_malformed_plan {
	d := decision with input as {"intent": clean_input.intent, "plan": {}, "repo": clean_input.repo, "risk": clean_input.risk}
	d.decision == "DENY"
}
