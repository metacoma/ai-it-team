from __future__ import annotations

import pytest

from openhands import OpenHandsInstance, OpenHandsRoleRunner
from openhands_langgraph.nodes import run_openhands_role_node

pytestmark = pytest.mark.asyncio


async def test_run_openhands_role_node_appends_serializable_result(fake_openhands_server) -> None:
    instance = OpenHandsInstance(fake_openhands_server.endpoint, default_model="openai/coder")
    runner = OpenHandsRoleRunner(instance, summary_max_attempts=1)

    state = {
        "user_task": "study repo",
        "role": "scout",
        "repository": "metacoma/freeplane_plugin_grpc",
        "role_run_options": {
            "start_poll_interval": 0,
            "websocket_retry_seconds": 1,
            "terminal_grace_seconds": 0,
        },
    }

    update = await run_openhands_role_node(
        state,
        config={"configurable": {"openhands_runner": runner}},
    )

    assert update["final_status"] == "completed"
    assert update["final_answer"] == "main answer"
    assert update["errors"] == []
    assert len(update["role_results"]) == 1

    role_result = update["role_results"][0]
    assert role_result["role"] == "scout"
    assert role_result["conversation_id"] == fake_openhands_server.conversation_id
    assert role_result["summary"]["status"] == "completed"
    assert role_result["ok"] is True
    assert role_result["metrics"]["duration_seconds"] >= 0
    assert role_result["metrics"]["summary_attempt_count"] == 1
    assert role_result["metrics"]["answer_chars"] == len("main answer")
    assert update["last_role_metrics"]["role"] == "scout"

    # Stage 1 must still preserve the Stage 0 invariant: summary is a follow-up
    # message in the same conversation, not a new app-conversation/sandbox.
    assert len(fake_openhands_server.created_payloads) == 1
    assert len(fake_openhands_server.followup_payloads) == 1


async def test_run_openhands_role_node_reports_config_errors_in_state() -> None:
    update = await run_openhands_role_node({"user_task": "study repo", "role": "scout"})

    assert update["final_status"] == "failed"
    assert update["last_role_result"] is None
    assert update["errors"]
    assert "openhands_runner" in update["errors"][0]


async def test_single_role_graph_ainvoke_with_mock_openhands(fake_openhands_server) -> None:
    pytest.importorskip("langgraph")

    from openhands_langgraph import build_single_role_graph

    instance = OpenHandsInstance(fake_openhands_server.endpoint, default_model="openai/coder")
    runner = OpenHandsRoleRunner(instance, summary_max_attempts=1)
    graph = build_single_role_graph()

    result = await graph.ainvoke(
        {
            "user_task": "study repo",
            "role": "scout",
            "role_run_options": {
                "start_poll_interval": 0,
                "websocket_retry_seconds": 1,
                "terminal_grace_seconds": 0,
            },
        },
        config={"configurable": {"openhands_runner": runner}},
    )

    assert result["final_status"] == "completed"
    assert result["last_role_result"]["role"] == "scout"
    assert result["last_role_result"]["summary"]["valid"] is True
    assert result["role_results"][0]["answer"] == "main answer"
    assert len(fake_openhands_server.created_payloads) == 1
    assert len(fake_openhands_server.followup_payloads) == 1
