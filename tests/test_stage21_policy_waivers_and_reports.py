from __future__ import annotations

from openhands_langgraph.nodes import _validate_team_lead_decision
from openhands_langgraph.reports import compact_report_summary


def _pass_result(role: str, report_id: str, role_report: dict | None = None) -> dict:
    return {
        "role": role,
        "role_instance": f"{role}-1",
        "report_id": report_id,
        "ok": True,
        "summary_action": "PASS",
        "summary": {"action": "PASS", "summary": f"{role} pass"},
        "role_report": role_report or {"role": role, "report_id": report_id, "action": "PASS"},
        "answer": "",
    }


def test_scout_compact_report_exposes_research_required_metadata() -> None:
    compact = compact_report_summary(
        {
            "role": "scout",
            "report_id": "scout-1",
            "action": "PASS",
            "facts": {
                "ci_failure": {"step": "Run Node.js integration tests"},
                "research_domains": ["@grpc/grpc-js version compatibility"],
                "research_questions": ["Does grpc-js 1.14.4 require channel options?"],
                "unknowns": ["exact upstream behavior"],
            },
        }
    )

    facts = compact["facts"]
    assert facts["research_required"] is True
    assert facts["research_domains"] == ["@grpc/grpc-js version compatibility"]
    assert facts["research_questions"] == ["Does grpc-js 1.14.4 require channel options?"]


def test_qa_compact_report_surfaces_blocking_targets_for_team_lead_judgment() -> None:
    compact = compact_report_summary(
        {
            "role": "qa",
            "report_id": "qa-1",
            "action": "PASS",
            "validation": {
                "validation_level": "targeted_unit",
                "targets": [
                    {"name": "unit", "required": True, "status": "passed"},
                    {"name": "nodejs_integration", "required": True, "status": "skipped", "reason": "no live server"},
                ],
                "gaps": [
                    {"target": "nodejs_integration", "blocking_candidate": True, "reason": "server not started"}
                ],
            },
        }
    )

    blocking = compact["validation"]["blocking_gaps"]
    assert any(item.get("name") == "nodejs_integration" for item in blocking if isinstance(item, dict))
    assert any(item.get("target") == "nodejs_integration" for item in blocking if isinstance(item, dict))


def test_research_required_blocks_downstream_without_explicit_team_lead_waiver() -> None:
    scout = _pass_result(
        "scout",
        "scout-report-1",
        {
            "role": "scout",
            "report_id": "scout-report-1",
            "action": "PASS",
            "facts": {"research_domains": ["grpc-js compatibility"], "research_questions": ["version behavior"]},
        },
    )
    state = {"role_results": [scout]}

    ok, reason = _validate_team_lead_decision(
        state,
        {"action": "RUN_ROLE", "next_role": "senior_staff_engineer", "role_instance": "senior_staff_engineer-1"},
    )

    assert ok is False
    assert "research is required" in (reason or "")


def test_team_lead_can_skip_research_with_explicit_structural_waiver() -> None:
    scout = _pass_result(
        "scout",
        "scout-report-1",
        {
            "role": "scout",
            "report_id": "scout-report-1",
            "action": "PASS",
            "research_required": True,
            "research_domains": ["grpc-js compatibility"],
        },
    )
    state = {"role_results": [scout]}

    ok, reason = _validate_team_lead_decision(
        state,
        {
            "action": "RUN_ROLE",
            "next_role": "senior_staff_engineer",
            "role_instance": "senior_staff_engineer-1",
            "accepted_report_ids": {"scout": "scout-report-1"},
            "policy_evaluation": {
                "can_skip_research": True,
                "skip_research_reason": "Local node_modules already contains the exact failing package code and no internet lookup is needed.",
            },
        },
    )

    assert ok is True, reason


def test_coder_without_architect_requires_explicit_architect_waiver_and_senior_report() -> None:
    research = _pass_result("research", "research-report-1")
    senior = _pass_result(
        "senior_staff_engineer",
        "senior-report-1",
        {
            "role": "senior_staff_engineer",
            "report_id": "senior-report-1",
            "action": "PASS",
            "fix_scope": "one-line change in grpc/nodejs/src/client.js",
            "files_to_change": ["grpc/nodejs/src/client.js"],
            "validation_strategy": "npm test + node integration test",
            "architect_waiver_candidate": True,
        },
    )
    state = {"role_results": [research, senior]}

    ok, reason = _validate_team_lead_decision(
        state,
        {"action": "RUN_ROLE", "next_role": "coder", "role_instance": "coder-1"},
    )
    assert ok is False
    assert "can_skip_architect" in (reason or "")

    ok, reason = _validate_team_lead_decision(
        state,
        {
            "action": "RUN_ROLE",
            "next_role": "coder",
            "role_instance": "coder-1",
            "accepted_report_ids": {"senior_staff_engineer": "senior-report-1"},
            "policy_evaluation": {
                "can_skip_architect": True,
                "skip_architect_reason": "Senior Staff produced exact one-line fix_scope, files_to_change, and validation_strategy.",
                "senior_staff_strategy_accepted": True,
                "implementation_scope_accepted": True,
            },
        },
    )
    assert ok is True, reason
