#!/usr/bin/env bash
# Replay a generated Jenkinsfile on the scratch controller and tail the result.
# Usage: ./replay.sh <path-to-Jenkinsfile>
set -euo pipefail

JENKINS_URL="${JENKINS_URL:-http://localhost:8080}"
JENKINS_AUTH="${JENKINS_AUTH:-admin:admin}"
FILE="${1:?usage: replay.sh <Jenkinsfile>}"
JOB="replay-$(date +%s)"

echo "==> waiting for controller at $JENKINS_URL ..."
for _ in $(seq 1 30); do
  curl -sf -o /dev/null -u "$JENKINS_AUTH" "$JENKINS_URL/login" && break
  sleep 5
done

SCRIPT_JSON=$(python3 -c "import json,sys; print(json.dumps(open(sys.argv[1]).read()))" "$FILE")
CRUMB=$(curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/crumbIssuer/api/json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['crumbRequestField']+':'+d['crumb'])")

echo "==> creating scratch pipeline job $JOB"
curl -s -o /dev/null -w "create: %{http_code}\n" -u "$JENKINS_AUTH" -H "$CRUMB" \
  -H 'Content-Type: application/xml' \
  --data-binary "<flow-definition><definition class='org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition'><script>$SCRIPT_JSON</script><sandbox>true</sandbox></definition></flow-definition>" \
  "$JENKINS_URL/createItem?name=$JOB"

echo "==> building"
curl -s -o /dev/null -w "build: %{http_code}\n" -u "$JENKINS_AUTH" -H "$CRUMB" -X POST "$JENKINS_URL/job/$JOB/build"
sleep 8
curl -s -u "$JENKINS_AUTH" "$JENKINS_URL/job/$JOB/lastBuild/api/json" | python3 -m json.tool | head -20

echo "==> deleting scratch job"
curl -s -o /dev/null -w "delete: %{http_code}\n" -u "$JENKINS_AUTH" -H "$CRUMB" -X POST "$JENKINS_URL/job/$JOB/doDelete"
