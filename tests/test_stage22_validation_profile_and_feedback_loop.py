from __future__ import annotations

import json
from pathlib import Path

from openhands_langgraph.prompts import build_qa_prompt, build_team_lead_decision_prompt
from openhands_langgraph.reports import compact_report_summary, parse_role_report, report_required_target_gaps


def test_validation_profile_gaps_compare_required_targets_to_qa_targets() -> None:
    profile = {
        "profile_id": "vp-1",
        "required_targets": [
            {"name": "unit", "required": True, "required_by": "ci"},
            {"name": "integration", "required": True, "required_by": "ci"},
        ],
    }
    validation = {
        "targets": [
            {"name": "unit", "status": "passed"},
            {"name": "integration", "status": "skipped", "reason": "no live server"},
        ]
    }

    gaps = report_required_target_gaps(profile, validation)

    assert gaps == [
        {
            "target": "integration",
            "status": "skipped",
            "blocking_candidate": True,
            "reason": "required target did not pass",
            "observed": {"name": "integration", "status": "skipped", "reason": "no live server"},
        }
    ]


def test_qa_report_compact_exposes_validation_profile_gaps_to_team_lead() -> None:
    report = {
        "role": "qa",
        "report_id": "qa-1",
        "action": "PASS",
        "validation_profile": {
            "profile_id": "vp-1",
            "required_targets": [
                {"name": "nodejs_integration", "required": True, "required_by": "ci"}
            ],
        },
        "validation": {
            "validation_level": "targeted_unit",
            "targets": [
                {"name": "nodejs_integration", "required": True, "status": "not_run", "reason": "server missing"}
            ],
        },
    }

    compact = compact_report_summary(report)

    assert compact["validation_profile"]["profile_id"] == "vp-1"
    assert compact["validation"]["profile_gaps"][0]["target"] == "nodejs_integration"
    assert compact["validation"]["blocking_gaps"][0]["name"] == "nodejs_integration"


def test_parse_qa_role_report_keeps_validation_profile_and_targets() -> None:
    answer = '''FINAL_ROLE_REPORT_JSON:
{
  "schema_version": "1.0",
  "role": "qa",
  "action": "PASS",
  "summary": "unit only",
  "risk_level": "medium",
  "blocking": false,
  "blocking_summary": [],
  "validation_profile": {"profile_id": "vp-1", "required_targets": [{"name": "integration", "required": true}]},
  "validation": {"targets": [{"name": "integration", "status": "skipped"}]},
  "qa_recommendation": {"ready_for_review": false, "recommended_next_role": "qa"}
}
'''
    report, source = parse_role_report("qa", answer=answer, role_instance="qa-1", fallback_report_id="qa-1:test")

    assert source == "final_role_report_json"
    assert report is not None
    assert report["validation_profile"]["profile_id"] == "vp-1"
    assert report["validation"]["targets"][0]["status"] == "skipped"


def test_team_lead_prompt_makes_validation_profile_and_pr_feedback_first_class() -> None:
    prompt = build_team_lead_decision_prompt(
        {
            "user_task": "fix PR checks",
            "validation_profile": {
                "profile_id": "vp-1",
                "required_targets": [{"name": "integration", "required": True, "required_by": "ci"}],
            },
        }
    )

    assert "validation_profile.required_targets" in prompt
    assert "compare validation.targets to validation_profile.required_targets" in prompt
    assert "PR checks as a new feedback loop" in prompt
    assert "route to scout for facts-only CI log collection" in prompt


def test_qa_prompt_requires_mapping_every_validation_profile_target() -> None:
    prompt = build_qa_prompt(
        {
            "user_task": "validate fix",
            "validation_profile": {
                "profile_id": "vp-1",
                "required_targets": [{"name": "ruby_integration", "required": True}],
            },
        }
    )

    assert "map every required target to validation.targets" in prompt
    assert "Do not omit required targets" in prompt
    assert "Validation profile / required target contract" in prompt


def test_scenario_replay_files_are_machine_readable_regressions() -> None:
    scenario_dir = Path(__file__).parent / "scenarios"
    scenarios = {path.stem: json.loads(path.read_text()) for path in scenario_dir.glob("*.json")}

    assert "qa_skipped_required_target" in scenarios
    assert scenarios["qa_skipped_required_target"]["expected_team_lead_behavior"]["can_review"] is False
    assert "publisher_failed_pr_checks_loop" in scenarios
    assert scenarios["publisher_failed_pr_checks_loop"]["expected_team_lead_behavior"]["recommended_next_role"] == "scout"
    assert "research_required_waiver" in scenarios
    assert "research" in scenarios["research_required_waiver"]["expected_team_lead_behavior"]["allowed_without_waiver"]


def test_publisher_report_compact_includes_pr_feedback_recommendation() -> None:
    compact = compact_report_summary(
        {
            "role": "publisher",
            "report_id": "publisher-1",
            "action": "NEED_FIX",
            "publish": {"pr_url": "https://github.com/o/r/pull/52", "head_sha": "abc"},
            "pr_checks": {"overall_status": "failed", "failing_checks": [{"name": "integration"}]},
            "pr_feedback": {"failed_check_logs_collected": True, "failing_steps": ["Run Node.js integration tests"]},
            "publisher_recommendation": {"recommended_next_role": "scout", "reason": "collect/triage failed CI check"},
        }
    )

    assert compact["pr_checks"]["overall_status"] == "failed"
    assert compact["pr_feedback"]["failing_steps"] == ["Run Node.js integration tests"]
    assert compact["publisher_recommendation"]["recommended_next_role"] == "scout"
