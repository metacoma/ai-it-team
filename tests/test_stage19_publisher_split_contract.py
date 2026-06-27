from openhands_langgraph.prompts import build_publisher_prompt


def test_publisher_uses_curl_for_pr_creation_and_gh_for_checks() -> None:
    prompt = build_publisher_prompt({"user_task": "publish fix"})

    assert "Create a PR with curl" in prompt
    assert "do not use gh pr create for creation" in prompt.lower()
    assert "gh pr checks" in prompt
    assert "gh for post-creation" in prompt
