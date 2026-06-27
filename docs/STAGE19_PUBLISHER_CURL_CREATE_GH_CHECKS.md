# Stage 19: Publisher creates PR with curl and checks it with gh

Publisher now follows a split GitHub publication contract:

1. Push the branch with git.
2. Create the GitHub pull request with `curl + GITHUB_TOKEN` using the GitHub REST API `POST /repos/{owner}/{repo}/pulls`.
3. Do not use `gh pr create` for PR creation.
4. Use `gh + GITHUB_TOKEN` for every post-creation operation: `gh pr view`, `gh pr list`, `gh pr checks --watch`, and final `gh pr checks --json ...`.
5. Return a typed publisher report containing sanitized PR creation evidence, PR metadata, and PR checks/statuses.

This preserves the explicit API-based PR creation path while still using `gh` for robust PR status/check handling.
