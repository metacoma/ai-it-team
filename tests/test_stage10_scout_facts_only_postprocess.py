from openhands_langgraph.nodes import _postprocess_role_result


def test_scout_postprocess_preserves_ok_and_summary() -> None:
    """Postprocess should preserve ok/summary_action and add role_report when present."""
    result = {
        "role": "scout",
        "ok": True,
        "summary_action": "PASS",
        "summary": {"action": "PASS", "summary": "Root cause hypothesis: bad attr handling."},
        "answer": "# Scout Context Report\n## Factual CI / Log Evidence\nExact error: boom\n## Relevant Files And Why They Are Relevant\nJsonHelper.java appears in stack trace.",
    }
    processed = _postprocess_role_result("scout", result)
    assert processed["ok"] is True
    assert processed["summary_action"] == "PASS"
    # Postprocess adds role_report and report_id
    assert "role_report" in processed or "report_id" in processed


def test_scout_postprocess_preserves_pass_when_no_report() -> None:
    """When there's no parseable role report, postprocess should preserve the original result."""
    result = {
        "role": "scout",
        "ok": True,
        "summary_action": "PASS",
        "summary": {"action": "PASS", "summary": "Scout complete."},
        "answer": "# Scout Context Report\nRoot cause hypothesis: attribute model missing.",
    }
    processed = _postprocess_role_result("scout", result)
    # Postprocess doesn't modify ok/summary_action when there's no report to parse
    assert processed["ok"] is True
    assert processed["summary_action"] == "PASS"
