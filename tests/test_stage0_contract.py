from __future__ import annotations

import json

import pytest

from openhands import OpenHandsInstance, OpenHandsRoleRunner, RoleRunSpec, __version__
from openhands.client import AppConversationStart, OpenHandsRunResult
from openhands.summary import SummaryAttempt


def test_public_version_is_exported() -> None:
    assert isinstance(__version__, str)
    assert __version__


def test_run_result_and_summary_attempt_are_serializable() -> None:
    start = AppConversationStart(
        conversation_id="conv",
        task_id="task",
        status="READY",
        session_api_key="secret-session",
    )
    run = OpenHandsRunResult(
        text="answer",
        status="finished",
        conversation_id="conv",
        start=start,
        seen_event_ids=frozenset({"1", "2"}),
    )
    attempt = SummaryAttempt(
        attempt=1,
        text='{"valid": true}',
        parsed_json={"valid": True},
        error=None,
        conversation_id="conv",
    )

    run_dict = run.to_dict()
    attempt_dict = attempt.to_dict(include_text=False)

    assert run_dict["has_answer"] is True
    assert run_dict["seen_event_count"] == 2
    assert run_dict["start"]["has_session_api_key"] is True
    assert "session_api_key" not in run_dict["start"]
    assert attempt_dict["valid"] is True
    assert "text" not in attempt_dict
    json.dumps({"run": run_dict, "attempt": attempt_dict})


@pytest.mark.asyncio
async def test_role_result_to_dict_is_langgraph_state_safe(fake_openhands_server) -> None:
    runner = OpenHandsRoleRunner(OpenHandsInstance(fake_openhands_server.endpoint, default_model="openai/coder"))

    result = await runner.run_role(
        role="scout",
        role_instance="scout_1",
        prompt="study repo",
        websocket_retry_seconds=1,
        terminal_grace_seconds=0,
        summary_max_attempts=1,
    )

    state = result.to_dict(include_answer=False, include_raw_summary=False)
    assert state["role"] == "scout"
    assert state["role_instance"] == "scout_1"
    assert state["ok"] is True
    assert state["summary_status"] == "completed"
    assert state["blocking"] is False
    assert "answer" not in state
    assert "raw_summary" not in state
    assert state["summary_attempt_count"] == 1
    json.dumps(state)


@pytest.mark.asyncio
async def test_parallel_failures_are_returned_when_fail_fast_false(fake_openhands_server) -> None:
    runner = OpenHandsRoleRunner(OpenHandsInstance(fake_openhands_server.endpoint, default_model="openai/coder"))

    results = await runner.run_roles_parallel(
        [RoleRunSpec(role="bad", role_instance="bad_1", prompt="x", conversation_params={"payload_file": "/definitely/missing/payload.json"})],
        fail_fast=False,
        max_concurrency=1,
    )

    assert len(results) == 1
    result = results[0]
    assert result.ok is False
    assert result.error
    assert result.summary_json.status == "failed"
    assert result.summary_json.blocking is True
    json.dumps(result.to_dict())
