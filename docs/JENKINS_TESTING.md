# Jenkins renderer + testing harness

The Jenkins renderer (`backend/src/ci_agent/pipeline/jenkins.py`) emits
declarative `Jenkinsfile`s from the same Pipeline IR as the YAML platforms —
one plan, four renderers. Because Jenkinsfiles are Groovy (not YAML), they get
their own validation path and test harness.

## What the renderer emits

- `pipeline { agent any; options { timestamps() }; stages { … } }`, one stage
  per IR job, `sh` steps per IR command, `post { always { cleanWs()? } }`
  only when the workspace step exists in the IR.
- Tool installs become explicit `sh "pip install <tool>==<version>"` steps —
  no shared-library magic, so the file is reviewable line by line.
- Secrets are referenced as `credentials('…')` bindings, never literals; the
  workflow-security validator rejects literal-looking secrets in `sh` strings.

## Validation

1. **IR schema** — same gate as every platform (invalid IR never renders).
2. **Structural Groovy check** (`validation/schema_checks.py::validate_jenkinsfile`):
   balanced braces/parens, required `pipeline/agent/stages` blocks, no
   `script {}` escapes hatch unless the plan explicitly requested scripting.
3. **Security checks** — same `security_checks.py` rules adapted to `sh` steps
   (no `curl … | sh`, no unpinned installs, least-privilege credentials).
4. **actionlint** does not apply (GitHub-only); the runner records
   `provenance.runner: not-applicable` for Jenkins runs.

## Test harness

- Golden: `backend/tests/golden/expected/*.jenkinsfile` — byte-compared;
  regenerate with `python backend/tests/golden/regen.py` after intentional
  changes (same flow as YAML goldens).
- Fixture scaffold: `examples/jenkins/` contains a minimal agent + controller
  setup to replay a generated Jenkinsfile:
  - `examples/jenkins/docker-compose.yml` — ephemeral controller with a
    suggested-plugin set pinned.
  - `examples/jenkins/replay.sh` — pushes a generated Jenkinsfile to a scratch
    multibranch job and tails the build log.
- Unit coverage: `backend/tests/unit/test_renderers.py` asserts stage/step
  mapping, credential bindings, and the no-`script`-block default.

## Running the harness

```bash
cd examples/jenkins
docker compose up -d                 # controller on :8080, agent attached
./replay.sh ../../backend/tests/golden/expected/python-api.jenkinsfile
docker compose down -v               # full cleanup
```

The replay script never touches production Jenkins: it creates a timestamped
scratch job, runs it once, prints the result, and deletes the job.
