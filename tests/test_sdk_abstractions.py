from __future__ import annotations

import pytest

from openhands import OpenHandsInstance, OpenHandsRoleRunner, RoleRunSpec

pytestmark = pytest.mark.asyncio


async def test_instance_run_returns_answer(fake_openhands_server) -> None:
    instance = OpenHandsInstance(
        endpoint=fake_openhands_server.endpoint,
        default_model="openai/coder",
    )

    result = await instance.run(
        prompt="study repo",
        start_poll_interval=0,
        websocket_retry_seconds=1,
        terminal_grace_seconds=0,
    )

    assert result.text == "main answer"
    assert fake_openhands_server.created_payloads == [
        {
            "initial_message": {"content": [{"type": "text", "text": "study repo"}]},
            "llm_model": "openai/coder",
        }
    ]


async def test_instance_create_conversation_and_followup(fake_openhands_server) -> None:
    instance = OpenHandsInstance(
        endpoint=fake_openhands_server.endpoint,
        default_model="openai/coder",
    )

    conversation = await instance.create_conversation(
        prompt="study repo",
        start_poll_interval=0,
    )
    main = await conversation.wait_finished(
        websocket_retry_seconds=1,
        terminal_grace_seconds=0,
    )
    followup = await conversation.send_message(
        "summarize as JSON",
        known_event_ids=main.seen_event_ids,
        websocket_retry_seconds=1,
        terminal_grace_seconds=0,
    )

    assert main.text == "main answer"
    assert followup.text.startswith('{"valid": true')
    assert len(fake_openhands_server.created_payloads) == 1
    assert len(fake_openhands_server.followup_payloads) == 1


async def test_role_runner_parallel_runs_independent_conversations(fake_openhands_server_factory) -> None:
    server_a = await fake_openhands_server_factory(conversation_id="conv-a", task_id="task-a")
    server_b = await fake_openhands_server_factory(conversation_id="conv-b", task_id="task-b")

    runner_a = OpenHandsRoleRunner(OpenHandsInstance(server_a.endpoint, default_model="openai/architect"))
    runner_b = OpenHandsRoleRunner(OpenHandsInstance(server_b.endpoint, default_model="openai/architect"))

    result_a, result_b = await runner_a.run_roles_parallel(
        [
            RoleRunSpec(role="architect", role_instance="architect_A", prompt="plan A"),
        ],
        max_concurrency=1,
        websocket_retry_seconds=1,
        terminal_grace_seconds=0,
        summary_max_attempts=1,
    ), await runner_b.run_roles_parallel(
        [
            RoleRunSpec(role="architect", role_instance="architect_B", prompt="plan B"),
        ],
        max_concurrency=1,
        websocket_retry_seconds=1,
        terminal_grace_seconds=0,
        summary_max_attempts=1,
    )

    a = result_a[0]
    b = result_b[0]
    assert a.role_instance == "architect_A"
    assert b.role_instance == "architect_B"
    assert a.conversation_id == "conv-a"
    assert b.conversation_id == "conv-b"
    assert len(server_a.created_payloads) == 1
    assert len(server_b.created_payloads) == 1
