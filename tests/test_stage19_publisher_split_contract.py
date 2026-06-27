from openhands_langgraph.prompts import build_publisher_prompt


def test_publisher_uses_curl_for_pr_creation_and_gh_for_checks() -> None:
    prompt = build_publisher_prompt({"user_task": "publish fix"})

    assert "Create the PR with `curl` + `GITHUB_TOKEN`" in prompt
    assert "POST /repos/{owner}/{repo}/pulls" in prompt
    assert "Do not use `gh pr create`" in prompt
    assert "gh pr view --json number,url,headRefName,headRefOid,baseRefName,state" in prompt
    assert "gh pr checks" in prompt
    assert "Raw GitHub REST API shell calls are allowed only for the PR creation step" in prompt
