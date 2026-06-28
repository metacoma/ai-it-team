from __future__ import annotations

from types import SimpleNamespace

from openhands_langgraph.role_catalog import (
    ROLE_CATALOG,
    TEAM_LEAD_ALLOWED_ROLES,
    capability_matrix_text,
    capabilities_for_role,
    role_contract_footer,
)
from openhands_langgraph.work_order_policy import (
    is_external_publication_order,
    surface_policy_matrix_text,
    validate_work_order_role_selection,
)


def test_role_catalog_is_single_source_for_allowed_roles_and_capabilities() -> None:
    assert "publisher" in TEAM_LEAD_ALLOWED_ROLES
    assert set(ROLE_CATALOG) == set(TEAM_LEAD_ALLOWED_ROLES)
    assert "bounded_external_publication" in capabilities_for_role("publisher")
    assert "edit_files" not in capabilities_for_role("scout")


def test_prompt_matrices_are_generated_from_catalog_and_surface_policy() -> None:
    capability_matrix = capability_matrix_text()
    surface_matrix = surface_policy_matrix_text()

    assert "- scout:" in capability_matrix
    assert "- publisher:" in capability_matrix
    assert "external_publication" in surface_matrix
    assert "documentation_gate" in surface_matrix


def test_role_contract_footer_explains_future_role_extension_point() -> None:
    known = role_contract_footer("coder")
    unknown = role_contract_footer("linux_admin")

    assert "allowed_typed_capabilities" in known
    assert "edit_files" in known
    assert "add it to role_catalog.py" in unknown


def test_work_order_policy_rejects_coder_for_publish_only_order() -> None:
    decision = SimpleNamespace(
        next_role="coder",
        capabilities_required=[],
        work_order={
            "change_surface": "external_publication",
            "execution_strategy": "direct_external_api",
        },
    )

    ok, reason = validate_work_order_role_selection(decision, "coder")

    assert ok is False
    assert reason is not None
    assert "external publication" in reason.lower()


def test_work_order_policy_allows_publisher_for_publish_only_order() -> None:
    decision = SimpleNamespace(
        next_role="publisher",
        capabilities_required=["bounded_external_publication"],
        work_order={
            "change_surface": "external_publication",
            "execution_strategy": "direct_external_api",
        },
    )

    assert is_external_publication_order(decision) is True
    assert validate_work_order_role_selection(decision, "publisher") == (True, None)
