# Stage 17: Publisher waits for PR checks/statuses

The Publisher role now owns the publication loop after Team Lead explicitly approves publishing:

1. Inspect the final diff and publish only relevant changes.
2. Push a safe feature branch.
3. Create or find the GitHub pull request using `gh` and `GITHUB_TOKEN`.
4. Capture PR number, URL, head ref, head SHA, base branch, and commit SHA.
5. Poll PR checks with `gh pr checks`, including a final machine-readable JSON read.
6. Return a typed `publisher` report containing `publish` and `pr_checks`.

Publisher must not treat PR creation alone as delivery completion. Team Lead receives the Publisher report and decides whether to stop completed or continue corrective work.

## Required report fields

```json
{
  "role": "publisher",
  "action": "PASS",
  "publish": {
    "branch": "feature/example",
    "commit": "...",
    "head_sha": "...",
    "base": "main",
    "pr_number": 123,
    "pr_url": "https://github.com/owner/repo/pull/123",
    "pushed": true,
    "pr_created": true,
    "existing_pr": false
  },
  "pr_checks": {
    "overall_status": "passed",
    "head_sha": "...",
    "waited": true,
    "timeout_seconds": 1800,
    "poll_interval_seconds": 30,
    "check_runs": [],
    "commit_status": {"state": "success", "statuses": []},
    "failing_checks": [],
    "pending_checks": [],
    "checked_at": "..."
  }
}
```

## Outcomes

- `ACTION: PASS`: PR exists and checks/statuses completed successfully.
- `ACTION: NEED_FIX`: PR checks/statuses failed, cancelled, timed out in a way likely requiring code/test changes, or CI result requires another engineering iteration.
- `ACTION: BLOCKER`: publishing or check discovery cannot proceed because of GitHub/GITHUB_TOKEN/gh/push limitations.

Team Lead should choose `STOP_COMPLETED` only after accepting the Publisher report and setting `policy_evaluation.can_complete=true` plus `publisher_pr_checks_accepted=true`.
