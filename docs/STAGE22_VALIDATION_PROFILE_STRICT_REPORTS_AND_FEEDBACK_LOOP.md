# Stage 22 — Validation Profile, Strict Reports, Scenario Replay, PR Feedback Loop

This stage moves the workflow away from prose/regex-driven decisions and toward
policy-driven Team Lead decisions based on typed role reports.

## P0: Validation Profile

Specialist roles can now emit a `validation_profile` in `FINAL_ROLE_REPORT_JSON`.
The profile is a required-target contract discovered from CI workflows, README
instructions, package scripts, helper scripts, runtime services, and the original
failure context.

Expected shape:

```json
{
  "validation_profile": {
    "profile_id": "validation-profile-1",
    "ci_workflows": [".github/workflows/integration.yml"],
    "required_targets": [
      {
        "name": "nodejs_integration_tests",
        "required": true,
        "required_by": "ci",
        "category": "integration",
        "commands": ["npm run test:integration"],
        "environment": ["Freeplane", "gRPC server"],
        "setup": ["start Freeplane under Xvfb"],
        "env": ["FREEPLANE_HOST", "FREEPLANE_PORT"],
        "source": "ci"
      }
    ],
    "runtime_services": [],
    "startup_scripts": [],
    "required_env": [],
    "notes": []
  }
}
```

Scout should establish the initial profile. Research, Senior Staff, and Architect
may refine it. QA must map every required target into `validation.targets` with
`passed`, `failed`, `skipped`, or `not_run` status.

## P1: Strict role reports

Every specialist prompt asks for a `FINAL_ROLE_REPORT_JSON` footer. The parser
keeps typed role reports in `role_report` and compact summaries expose only the
parts Team Lead needs.

Important additions:

- `validation_profile` is available on all role reports.
- QA reports now support target matrices and profile gap comparison.
- Publisher reports now support `pr_feedback` and `publisher_recommendation`.

LangGraph still keeps compatibility with old summaries, but typed reports are
the preferred interface.

## P2: Scenario replay tests

Real workflow failures should become regression scenarios under `tests/scenarios`.
Stage 22 adds scenarios for:

- QA passing while a required target was skipped.
- Publisher reporting failed PR checks and recommending a corrective loop.
- Scout marking research required and requiring Team Lead waiver to skip it.

The goal is to turn every orchestration failure into a durable test case.

## P4: PR checks feedback loop

Publisher reports failed/pending/timed-out PR checks as structured feedback:

```json
{
  "pr_checks": {
    "overall_status": "failed",
    "failing_checks": []
  },
  "pr_feedback": {
    "failed_check_logs_collected": true,
    "failure_summary": "...",
    "failing_steps": [],
    "log_urls": []
  },
  "publisher_recommendation": {
    "ready_to_complete": false,
    "recommended_next_role": "scout",
    "reason": "collect failed CI logs as a new facts-only input"
  }
}
```

Team Lead should treat failed PR checks as a new feedback loop. If failing logs
are not already collected, it should usually route to Scout first, not retry
Coder blindly.
