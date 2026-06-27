from openhands_langgraph.prompts import (
    build_publisher_prompt,
    build_role_summary_instructions,
    build_team_lead_decision_prompt,
)
from openhands_langgraph.reports import compact_report_summary, parse_role_report
from openhands_langgraph.nodes import _postprocess_role_result


def test_publisher_prompt_requires_waiting_for_pr_checks() -> None:
    prompt = build_publisher_prompt({"user_task": "publish fix"})

    assert "After the PR exists" in prompt
    assert "gh pr checks" in prompt
    assert "gh pr view --json number,url,headRefName,headRefOid,baseRefName,state" in prompt
    assert "PUBLISHER_CHECK_TIMEOUT_SECONDS" in prompt
    assert "gh auth status" in prompt
    assert "POST /repos/{owner}/{repo}/pulls" in prompt
    assert "Do not use `gh pr create`" in prompt
    assert "curl" in prompt
    assert "pr_checks.overall_status" in prompt
    assert "do not pretend CI passed" in prompt
    assert "gh pr checks" in prompt


def test_publisher_summary_instructions_require_pr_checks() -> None:
    instructions = build_role_summary_instructions("publisher")

    assert "extra key pr_checks" in instructions
    assert "overall_status" in instructions
    assert "head_sha" in instructions
    assert "failing_checks" in instructions
    assert "Copy the pr_checks object" in instructions


def test_team_lead_prompt_requires_publisher_checks_acceptance() -> None:
    prompt = build_team_lead_decision_prompt({"user_task": "publish fix"})

    assert "publisher_pr_checks_accepted" in prompt
    assert "can_complete" in prompt
    assert "publish.pr_url" in prompt
    assert "pr_checks" in prompt


def test_publisher_report_schema_includes_pr_checks() -> None:
    answer = '''# Publisher Report
FINAL_ROLE_REPORT_JSON:
{
  "schema_version": "1.0",
  "role": "publisher",
  "action": "PASS",
  "summary": "PR created and checks passed",
  "risk_level": "low",
  "blocking": false,
  "blocking_summary": [],
  "published_change_set_id": "coder-1-attempt-2",
  "publish": {"branch": "fix/demo", "commit": "abc", "head_sha": "abc", "pr_url": "https://github.com/o/r/pull/1", "pushed": true, "pr_created": true},
  "pr_checks": {"overall_status": "passed", "head_sha": "abc", "waited": true, "check_runs": [{"name": "ci", "status": "completed", "conclusion": "success"}], "commit_status": {"state": "success"}, "failing_checks": [], "pending_checks": []}
}
'''
    report, source = parse_role_report("publisher", answer=answer, role_instance="publisher-1", fallback_report_id="publisher-1:test")

    assert source == "final_role_report_json"
    assert report is not None
    assert report["pr_checks"]["overall_status"] == "passed"
    compact = compact_report_summary(report)
    assert compact["pr_checks"]["head_sha"] == "abc"


def test_publisher_postprocess_promotes_pr_checks_to_summary() -> None:
    result = {
        "role": "publisher",
        "role_instance": "publisher-1",
        "conversation_id": "conv",
        "ok": True,
        "summary_action": "PASS",
        "summary": {"action": "PASS", "summary": "PR ok"},
        "answer": '''FINAL_ROLE_REPORT_JSON:
{"role":"publisher","action":"PASS","summary":"ok","risk_level":"low","blocking":false,"blocking_summary":[],"publish":{"pr_url":"https://github.com/o/r/pull/1","head_sha":"abc"},"pr_checks":{"overall_status":"passed","head_sha":"abc","waited":true,"check_runs":[],"commit_status":{"state":"success"},"failing_checks":[],"pending_checks":[]}}''',
    }

    processed = _postprocess_role_result("publisher", result)

    assert processed["summary"]["pr_checks"]["overall_status"] == "passed"
    assert processed["role_report"]["publish"]["head_sha"] == "abc"

from openhands_langgraph.nodes import _publisher_pr_checks_ok, _validate_team_lead_decision


def test_publisher_pass_without_pr_checks_is_rewritten_to_need_fix() -> None:
    result = {
        "role": "publisher",
        "role_instance": "publisher-1",
        "conversation_id": "conv",
        "ok": True,
        "summary_action": "PASS",
        "summary": {"action": "PASS", "summary": "PR #52 created but no checks reported"},
        "answer": "PR #52 created: https://github.com/o/r/pull/52",
    }

    processed = _postprocess_role_result("publisher", result)

    assert processed["summary_action"] == "NEED_FIX"
    assert processed["publisher_pr_checks_contract_violation"] is True
    assert "pr_checks" in processed["publisher_pr_checks_contract_reason"]


def test_stop_completed_requires_publisher_pr_checks_acceptance() -> None:
    state = {
        "role_results": [
            {
                "role": "publisher",
                "role_instance": "publisher-1",
                "ok": True,
                "summary_action": "PASS",
                "summary": {"action": "PASS", "summary": "PR created only"},
                "answer": "PR created",
            }
        ]
    }

    ok, reason = _validate_team_lead_decision(
        state,
        {
            "action": "STOP_COMPLETED",
            "policy_evaluation": {"can_complete": True, "publisher_pr_checks_accepted": True},
        },
    )

    assert ok is False
    assert "publisher PR checks" in reason


def test_publisher_pr_checks_ok_accepts_successful_gh_result() -> None:
    result = {
        "role": "publisher",
        "role_instance": "publisher-1",
        "ok": True,
        "summary_action": "PASS",
        "summary": {
            "action": "PASS",
            "summary": "PR checks passed",
            "publish": {"pr_url": "https://github.com/o/r/pull/1", "head_sha": "abc"},
            "pr_checks": {
                "overall_status": "passed",
                "head_sha": "abc",
                "waited": True,
                "check_runs": [{"name": "ci", "status": "completed", "conclusion": "success"}],
                "commit_status": {"state": "success"},
                "failing_checks": [],
                "pending_checks": [],
            },
        },
    }

    ok, reason = _publisher_pr_checks_ok(result)

    assert ok is True
    assert reason is None
