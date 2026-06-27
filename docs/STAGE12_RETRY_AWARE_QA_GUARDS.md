# Stage 12: Retry-aware QA guards

Stage 12 fixes a Team Lead routing false negative in retry cycles.

A valid workflow can contain:

```text
coder PASS
qa NEED_FIX
coder RETRY/PASS
qa PASS
team_lead -> reviewer
```

The reviewer guard must evaluate the **latest QA PASS after the latest coder PASS**. It must not accidentally evaluate the older QA NEED_FIX result, and it must not rely on stale role-specific snapshots when the append-only `role_results` history contains the true order.

## Changes

- `role_results` is now the ordering source of truth for latest-role selection.
- QA validation for reviewer/publisher is selected after the latest coder PASS.
- A QA PASS before a later coder retry no longer unlocks reviewer.
- Non-blocking validation gaps no longer fail QA evidence when real targeted runtime/integration evidence exists.

Example non-blocking gap:

```text
Ruby integration tests not run - only Python failing integration test executed
```

This is a reviewer risk input, not an automatic graph blocker, when QA still reports:

```json
{
  "build_ran": true,
  "build_passed": true,
  "tests_run": true,
  "tests_passed": true,
  "validation_level": "targeted_integration"
}
```

The graph still blocks gaps that prove QA skipped required validation by excuse, such as `out of scope`, `syntax-only`, or missing upstream/core checkout.
