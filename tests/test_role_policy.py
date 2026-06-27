from __future__ import annotations

from types import SimpleNamespace

from openhands_langgraph.role_policy import (
    ROLE_CAPABILITIES,
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
