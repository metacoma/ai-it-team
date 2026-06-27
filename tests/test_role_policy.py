from __future__ import annotations

from types import SimpleNamespace

from openhands_langgraph.role_policy import (
    ROLE_CAPABILITIES,
    publisher_has_structured_unrelated_check_failure,
    validate_team_lead_assignment_policy,
)


def test_scout_assignment_allows_build_system_prose_without_forbidden_words() -> None:
    decision = SimpleNamespace(
        next_role="scout",
        instructions="Identify the programming language and build system used in the project.",
        reason="Collect factual repository context before implementation.",
    )

    assert validate_team_lead_assignment_policy(decision) == (True, None)


def test_typed_capability_matrix_rejects_capability_not_owned_by_role() -> None:
    decision = SimpleNamespace(
        next_role="scout",
        capabilities_required=["read_repo", "edit_files"],
    )

    ok, reason = validate_team_lead_assignment_policy(decision)

    assert ok is False
    assert reason is not None
    assert "edit_files" in reason


def test_scout_capabilities_are_read_only() -> None:
    assert "inspect_ci_metadata" in ROLE_CAPABILITIES["scout"]
    assert "edit_files" not in ROLE_CAPABILITIES["scout"]
    assert "run_validation" not in ROLE_CAPABILITIES["scout"]


def test_publisher_structured_unrelated_failed_checks_are_acceptable() -> None:
    result = {
        "summary": {
            "action": "PASS",
            "pr_checks": {
                "overall_status": "failed",
                "head_sha": "abc123",
                "waited": True,
                "failing_checks": ["tests / 3.12"],
                "failure_analysis": {
                    "classification": "pre_existing_codebase",
                    "change_related": False,
                    "evidence": [
                        "Failure is ImportError in an existing test module unrelated to .github/workflows/tests.yml"
                    ],
                    "failing_tests": ["test_stage8_qa_validation_evidence.py"],
                    "requires_coder_fix": False,
                },
            },
        }
    }

    ok, reason = publisher_has_structured_unrelated_check_failure(result)

    assert ok is True
    assert reason is not None
    assert "unrelated" in reason or "pre-existing" in reason


def test_publisher_failed_checks_without_structured_attribution_are_not_acceptable() -> None:
    result = {
        "summary": {
            "action": "PASS",
            "pr_checks": {
                "overall_status": "failed",
                "failing_checks": ["tests / 3.12"],
            },
        }
    }

    ok, reason = publisher_has_structured_unrelated_check_failure(result)

    assert ok is False
    assert reason is not None
    assert "failure_analysis" in reason
