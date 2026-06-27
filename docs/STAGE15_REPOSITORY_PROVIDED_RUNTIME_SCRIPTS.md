# Stage 15: Repository-provided runtime scripts are mandatory QA setup

v45 closes a QA loophole where runtime/integration tests were reported as
"CI-only" even though the repository contained scripts and workflow commands for
starting the required Freeplane/Xvfb/gRPC runtime.

## Rule

For CI/runtime/integration/smoke failures, QA must inspect and use repository
validation entry points before claiming that local validation is impossible:

- `.github/workflows/*`
- `scripts/*`
- `Makefile` targets
- Gradle tasks
- shell helpers
- Xvfb/openbox/GUI startup wrappers
- Freeplane startup scripts
- gRPC readiness checks
- language-specific test scripts

Missing variables such as `FREEPLANE_HOST` are setup inputs, not excuses. QA
must attempt to start the live service locally, set the expected host/port, and
run the suite.

## Blocked QA PASS patterns

A QA `PASS` is rejected when the QA report says things like:

- "cannot be validated locally without starting Freeplane/Xvfb/gRPC"
- "requires the full CI pipeline"
- "cannot run in this sandbox"
- "Ruby integration tests excluded without FREEPLANE_HOST"
- "Python smoke tests require a live Freeplane gRPC server"
- "the fix is structurally correct" without runtime evidence

These are valid blockers only after concrete install/setup/script attempts are
reported. Without those attempts, QA must return `NEED_FIX` or `BLOCKER`, not
`PASS`.

## Guard behavior

The LangGraph QA guard now inspects both compact summary and full QA answer for
these runtime-deferment phrases, because local LLM summaries can omit validation
gaps from the structured JSON object.

Reviewer guards also reject reviewer reports that accept such QA gaps instead of
returning `NEED_FIX`/`BLOCKER`.
