# Stage 20: Policy-driven QA gap decisions and Publisher PR checks contract

v50 keeps LangGraph as a structural safety kernel while making Team Lead own the semantic delivery decision.

## QA

QA reports are recommendations, not automatic approvals. Team Lead must inspect typed QA report fields:

- validation_level
- targets
- gaps
- validation_gaps
- qa_recommendation

For runtime/CI/smoke/integration tasks, `targeted_unit` is insufficient unless the original target was unit-only. Skipped required targets are not passing tests. If QA reports integration tests skipped gracefully, smoke tests not executed end-to-end, missing live server/runtime, or deferred CI validation, Team Lead should reject QA PASS and retry QA unless setup attempts failed and the risk is explicitly accepted.

## Publisher

Publisher must create the PR with `curl + GITHUB_TOKEN`, then use `gh` for post-creation inspection and check waiting.

Publisher PASS is structurally invalid unless it returns `pr_checks` showing:

- head SHA present
- checks/statuses discovered
- checks waited for
- overall status passed/success
- no failing checks
- no pending checks

Team Lead may STOP_COMPLETED only after `policy_evaluation.can_complete=true`, `publisher_pr_checks_accepted=true`, and a Publisher report with accepted PR check evidence.
