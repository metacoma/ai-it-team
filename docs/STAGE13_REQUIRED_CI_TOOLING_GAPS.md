# Stage 13: Required CI tooling gaps

v43 tightens QA validation after a failure mode where QA ran Python smoke tests
but skipped Ruby integration tests because Ruby and Bundler were not installed in
the sandbox.

## Rule

A missing installable validation tool is not a non-blocking validation gap.

If the CI workflow, README, build scripts, or original failure path includes a
language/runtime test suite, QA must either:

1. install the required toolchain and run the suite, or
2. return `ACTION: NEED_FIX` / `ACTION: BLOCKER` after documenting concrete
   install/setup attempts and exact errors.

QA must not return `ACTION: PASS` with gaps such as:

- `Ruby integration tests not run — Ruby and bundler are not installed`
- `these should be verified in the actual CI pipeline`
- `Ruby tests not run because bundler is missing`

## Guard behavior

LangGraph now blocks reviewer/publisher when QA `validation_gaps` or compact
summary text indicates that a required CI/build/runtime suite was skipped because
an installable runtime/package manager was missing.

Non-blocking gaps are still allowed after real targeted integration validation,
but only when they are clearly outside the original task/failed CI path and are
not caused by missing installable validation tools.
