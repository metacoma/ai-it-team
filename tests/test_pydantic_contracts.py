from __future__ import annotations

import json

import pytest

from openhands.models import RoleRunSpec, RoleSummary
from openhands.summary import parse_role_summary
from openhands.client import OpenHandsError


def test_role_summary_validates_and_serializes() -> None:
    summary = parse_role_summary(
        '{"valid": true, "status": "completed", "summary": "ok", "action": null, "risk_level": "low", "blocking": false, "blocking_summary": []}'
    )

    assert isinstance(summary, RoleSummary)
    assert summary.status == "completed"
    assert summary.risk_level == "low"
    json.dumps(summary.model_dump(mode="json"))


def test_role_summary_rejects_missing_summary() -> None:
    with pytest.raises(OpenHandsError, match="RoleSummary"):
        parse_role_summary('{"valid": true, "status": "completed"}')


def test_role_run_spec_is_pydantic_model() -> None:
    spec = RoleRunSpec(role="architect", role_instance="architect_A", prompt="plan")

    assert spec.role == "architect"
    assert spec.model_dump(mode="json")["role_instance"] == "architect_A"


def test_role_summary_parser_recovers_missing_final_brace() -> None:
    from openhands.summary import parse_role_summary

    text = '{"action": "PASS", "summary": "Readable scout summary without a final brace"'

    parsed = parse_role_summary(text)

    assert parsed.action == "PASS"
    assert parsed.summary == "Readable scout summary without a final brace"
    assert parsed.valid is True
