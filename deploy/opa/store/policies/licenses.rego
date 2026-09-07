# Dependency license policy (Phase 2: "license policy"). The license list is
# populated by discovery (lockfile metadata) and SCA; unknown licenses pass
# here and are flagged by the SCA step instead of blocking the run.
package ciagent.policy

deny[{"rule": "LICENSE_DENIED", "message": msg}] {
	input.plan.licenses[_] == lic
	data.denied.licenses[_] == lic
	msg := sprintf("dependency license '%s' is denied by organization policy", [lic])
}
