# Stage 18: Publisher uses curl for PR creation and gh for PR checks

Publisher publication now uses a split contract: create the PR with `curl + GITHUB_TOKEN`, then use `gh + GITHUB_TOKEN` for PR discovery/view/checks/watch.

Required behavior:

1. Ensure `gh` is installed. If missing, install it when reasonable; otherwise return BLOCKER.
2. Authenticate non-interactively with `GITHUB_TOKEN` and verify with `gh auth status` without printing secrets.
3. Push the prepared branch.
4. Create the PR with `curl` against `POST /repos/{owner}/{repo}/pulls` using `GITHUB_TOKEN`, or find an existing PR with `gh pr view` / `gh pr list`.
5. Capture PR number, URL, head SHA, branch, and base branch with `gh pr view --json number,url,headRefName,headRefOid,baseRefName,state`.
6. Watch PR checks with `gh pr checks --watch` within a bounded timeout.
7. Read final machine-readable check state with `gh pr checks --json bucket,completedAt,description,event,link,name,startedAt,state,workflow`.
8. Return `publish` and `pr_checks` in `FINAL_ROLE_REPORT_JSON`.

Publisher must not treat PR creation alone as successful delivery. Team Lead receives the Publisher report and decides whether to stop completed or continue corrective work.


## v49 update

PR creation must be performed with `curl + GITHUB_TOKEN`. `gh pr create` is intentionally forbidden for the creation step. After the PR exists, all PR metadata/check/status/watch operations should use `gh`: `gh pr view`, `gh pr list`, and `gh pr checks --watch`.
