from __future__ import annotations

import pytest

from openhands.client import run_conversation_and_collect
from openhands.role import run_role_with_summary

pytestmark = pytest.mark.asyncio


async def test_run_conversation_collects_final_answer(fake_openhands_server) -> None:
    result = await run_conversation_and_collect(
        endpoint=fake_openhands_server.endpoint,
        prompt="study repo",
        llm_model="openai/coder",
        start_poll_interval=0,
        websocket_retry_seconds=1,
        terminal_grace_seconds=0,
    )

    assert result.text == "main answer"
    assert result.status == "finished"
    assert result.conversation_id == fake_openhands_server.conversation_id
    assert fake_openhands_server.created_payloads == [
        {
            "initial_message": {"content": [{"type": "text", "text": "study repo"}]},
            "llm_model": "openai/coder",
        }
    ]


async def test_role_summary_uses_same_conversation_not_new_sandbox(fake_openhands_server) -> None:
    result = await run_role_with_summary(
        endpoint=fake_openhands_server.endpoint,
        prompt="study repo",
        llm_model="openai/coder",
        start_poll_interval=0,
        websocket_retry_seconds=1,
        terminal_grace_seconds=0,
        summary_max_attempts=1,
    )

    assert result.answer == "main answer"
    assert result.summary_json.valid is True
    assert result.summary_json["status"] == "completed"

    # Only the main role creates an app-conversation. Summary must be a POST to
    # /api/conversations/{same_id}/events, not a second app-conversation/sandbox.
    assert len(fake_openhands_server.created_payloads) == 1
    assert len(fake_openhands_server.followup_payloads) == 1
    assert fake_openhands_server.followup_payloads[0]["role"] == "user"
    assert fake_openhands_server.followup_payloads[0]["run"] is True
    sent_text = fake_openhands_server.followup_payloads[0]["content"][0]["text"]
    assert "OpenHands answer to summarize" in sent_text
    assert "main answer" in sent_text


async def test_role_summary_retries_until_valid_json(fake_openhands_server_factory) -> None:
    server = await fake_openhands_server_factory(
        summary_event_batches=[
            [
                {"id": "bad-running", "kind": "ConversationStateUpdateEvent", "key": "execution_status", "value": "running"},
                {
                    "id": "bad-answer",
                    "kind": "MessageEvent",
                    "source": "agent",
                    "llm_message": {"role": "assistant", "content": [{"type": "text", "text": "not json"}]},
                },
                {"id": "bad-finished", "kind": "ConversationStateUpdateEvent", "key": "execution_status", "value": "finished"},
            ],
            [
                {"id": "good-running", "kind": "ConversationStateUpdateEvent", "key": "execution_status", "value": "running"},
                {
                    "id": "good-answer",
                    "kind": "MessageEvent",
                    "source": "agent",
                    "llm_message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": '{"valid": true, "status": "completed", "summary": "fixed", "action": null, "risk_level": null, "blocking": false, "blocking_summary": []}',
                            }
                        ],
                    },
                },
                {"id": "good-finished", "kind": "ConversationStateUpdateEvent", "key": "execution_status", "value": "finished"},
            ],
        ]
    )

    result = await run_role_with_summary(
        endpoint=server.endpoint,
        prompt="study repo",
        llm_model="openai/coder",
        start_poll_interval=0,
        websocket_retry_seconds=1,
        terminal_grace_seconds=0,
        summary_max_attempts=2,
    )

    assert result.summary_json.summary == "fixed"
    assert len(result.summary_attempts) == 2
    assert result.summary_attempts[0].error is not None
    assert result.summary_attempts[1].error is None
    assert len(server.created_payloads) == 1
    assert len(server.followup_payloads) == 2
    retry_text = server.followup_payloads[1]["content"][0]["text"]
    assert "Your previous response was not valid JSON" in retry_text
    assert "not json" in retry_text

async def test_title_is_patched_after_v1_conversation_is_ready(fake_openhands_server) -> None:
    result = await run_conversation_and_collect(
        endpoint=fake_openhands_server.endpoint,
        prompt="study repo",
        llm_model="openai/coder",
        title="scout: study repo",
        start_poll_interval=0,
        websocket_retry_seconds=1,
        terminal_grace_seconds=0,
    )

    assert result.text == "main answer"
    assert fake_openhands_server.created_payloads[0]["title"] == "scout: study repo"
    assert fake_openhands_server.patched_payloads == [{"title": "scout: study repo"}]
    assert result.start.raw_conversation["title"] == "scout: study repo"
