from openhands_langgraph.nodes import _postprocess_role_result


def test_scout_summary_diagnostic_wording_is_sanitized_when_answer_is_clean() -> None:
    result = {
        "role": "scout",
        "ok": True,
        "summary_action": "PASS",
        "summary": {"action": "PASS", "summary": "Root cause hypothesis: bad attr handling."},
        "answer": "# Scout Context Report\n## Factual CI / Log Evidence\nExact error: boom\n## Relevant Files And Why They Are Relevant\nJsonHelper.java appears in stack trace.",
    }
    processed = _postprocess_role_result("scout", result)
    assert processed["ok"] is True
    assert processed["scout_summary_sanitized"] is True
    assert "Root cause hypothesis" not in processed["summary"]["summary"]


def test_scout_answer_diagnostic_wording_fails_facts_only_contract() -> None:
    result = {
        "role": "scout",
        "ok": True,
        "summary_action": "PASS",
        "summary": {"action": "PASS", "summary": "Scout complete."},
        "answer": "# Scout Context Report\nRoot cause hypothesis: attribute model missing.",
    }
    processed = _postprocess_role_result("scout", result)
    assert processed["ok"] is False
    assert processed["summary_action"] == "NEED_FIX"
    assert processed["scout_facts_only_violation"] is True
