"""Tests for --conversation-list and --conversation-send CLI modes."""

from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


class TestConversationList:
    """Tests for --conversation-list mode."""

    async def test_list_conversations_returns_data(self) -> None:
        """Test that conversation-list returns conversation data."""
        from openhands_langgraph.cli import _list_conversations

        mock_client = AsyncMock()
        mock_client.search_app_conversations = AsyncMock(
            return_value=[
                {
                    "id": "conv-1",
                    "title": "Test conversation",
                    "llm_model": "openai/coder",
                    "execution_status": "finished",
                    "sandbox_id": "sandbox-1",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T01:00:00Z",
                },
                {
                    "id": "conv-2",
                    "title": "Another conversation",
                    "llm_model": "openai/assistant",
                    "execution_status": "running",
                    "sandbox_id": "sandbox-2",
                    "created_at": "2024-01-02T00:00:00Z",
                    "updated_at": "2024-01-02T01:00:00Z",
                },
            ]
        )

        args = MagicMock()
        args.endpoint = "http://test.local:3000"
        args.api_key = "test-key"

        with patch(
            "openhands_langgraph.cli.OpenHandsClient", return_value=mock_client
        ):
            result = await _list_conversations(args)

        assert result["total"] == 2
        assert len(result["conversations"]) == 2
        assert result["conversations"][0]["id"] == "conv-1"
        assert result["conversations"][0]["llm_model"] == "openai/coder"
        assert result["conversations"][0]["title"] == "Test conversation"
        assert result["conversations"][0]["status"] == "finished"

    async def test_list_conversations_dict_response(self) -> None:
        """Test pagination with dict response containing items."""
        from openhands_langgraph.cli import _list_conversations

        mock_client = AsyncMock()
        mock_client.search_app_conversations = AsyncMock(
            return_value={
                "items": [
                    {
                        "id": "conv-1",
                        "title": "Paginated conversation",
                        "llm_model": "openai/coder",
                        "execution_status": "finished",
                    }
                ],
                "next_page_id": None,
            }
        )

        args = MagicMock()
        args.endpoint = "http://test.local:3000"
        args.api_key = "test-key"

        with patch(
            "openhands_langgraph.cli.OpenHandsClient", return_value=mock_client
        ):
            result = await _list_conversations(args)

        assert result["total"] == 1
        assert result["conversations"][0]["id"] == "conv-1"

    async def test_list_conversations_empty(self) -> None:
        """Test listing when no conversations exist."""
        from openhands_langgraph.cli import _list_conversations

        mock_client = AsyncMock()
        mock_client.search_app_conversations = AsyncMock(return_value=[])

        args = MagicMock()
        args.endpoint = "http://test.local:3000"
        args.api_key = "test-key"

        with patch(
            "openhands_langgraph.cli.OpenHandsClient", return_value=mock_client
        ):
            result = await _list_conversations(args)

        assert result["total"] == 0
        assert result["conversations"] == []

    async def test_list_conversations_missing_fields(self) -> None:
        """Test that missing fields are handled gracefully."""
        from openhands_langgraph.cli import _list_conversations

        mock_client = AsyncMock()
        mock_client.search_app_conversations = AsyncMock(
            return_value=[
                {"id": "conv-minimal"},  # Only required field
            ]
        )

        args = MagicMock()
        args.endpoint = "http://test.local:3000"
        args.api_key = "test-key"

        with patch(
            "openhands_langgraph.cli.OpenHandsClient", return_value=mock_client
        ):
            result = await _list_conversations(args)

        assert result["total"] == 1
        assert result["conversations"][0]["id"] == "conv-minimal"
        assert result["conversations"][0]["title"] == ""
        assert result["conversations"][0]["llm_model"] == ""


class TestConversationSend:
    """Tests for --conversation-send mode."""

    async def test_send_message_basic(self) -> None:
        """Test sending a message without --wait."""
        from openhands_langgraph.cli import _send_conversation_message

        mock_instance = AsyncMock()
        mock_conversation = MagicMock()
        mock_conversation.conversation_id = "test-conv-id"
        mock_instance.attach_conversation = AsyncMock(return_value=mock_conversation)
        mock_instance.client = AsyncMock()
        mock_instance.client.get_app_conversation = AsyncMock(
            return_value=[{"llm_model": "openai/coder"}]
        )
        mock_instance.client.send_message_to_existing_conversation = AsyncMock(
            return_value={"success": True}
        )

        args = MagicMock()
        args.conversation_send = "test-conv-id"
        args.prompt = "Hello, assistant!"
        args.wait = False
        args.endpoint = "http://test.local:3000"
        args.api_key = "test-key"
        args.model = None

        with patch(
            "openhands_langgraph.cli.OpenHandsInstance", return_value=mock_instance
        ):
            result = await _send_conversation_message(args)

        assert result["conversation_id"] == "test-conv-id"
        assert result["message_sent"] == "Hello, assistant!"
        assert result["llm_model"] == "openai/coder"
        assert result.get("waited") is False
        assert "response" not in result

    async def test_send_message_with_wait(self) -> None:
        """Test sending a message with --wait flag."""
        from openhands_langgraph.cli import _send_conversation_message

        mock_instance = AsyncMock()
        mock_conversation = MagicMock()
        mock_conversation.conversation_id = "test-conv-id"
        mock_instance.attach_conversation = AsyncMock(return_value=mock_conversation)
        mock_instance.client = AsyncMock()
        mock_instance.client.get_app_conversation = AsyncMock(
            return_value=[{"llm_model": "openai/coder"}]
        )
        mock_instance.client.send_message_to_existing_conversation = AsyncMock(
            return_value={"success": True}
        )

        # Create a proper async iterator
        events = [
            {"kind": "ConversationStateUpdateEvent", "key": "execution_status", "value": "running"},
            {
                "kind": "MessageEvent",
                "llm_message": {"content": [{"type": "text", "text": "Hello from assistant!"}]},
            },
            {"kind": "ConversationStateUpdateEvent", "key": "execution_status", "value": "finished"},
        ]
        event_index = [0]

        class EventIterator:
            async def __anext__(self):
                if event_index[0] < len(events):
                    event = events[event_index[0]]
                    event_index[0] += 1
                    return event
                raise StopAsyncIteration()

            async def aclose(self):
                pass

        mock_event_iter = EventIterator()
        mock_instance.client.stream_v1_events = MagicMock(return_value=mock_event_iter)

        args = MagicMock()
        args.conversation_send = "test-conv-id"
        args.prompt = "Hello, assistant!"
        args.wait = True
        args.endpoint = "http://test.local:3000"
        args.api_key = "test-key"
        args.model = None
        args.raw_websocket = False
        args.websocket_retry_seconds = 1.0
        args.terminal_grace_seconds = 0.0
        args.show_events = False

        with patch(
            "openhands_langgraph.cli.OpenHandsInstance", return_value=mock_instance
        ):
            result = await _send_conversation_message(args)

        assert result["conversation_id"] == "test-conv-id"
        assert result["waited"] is True
        assert result["response"] == "Hello from assistant!"
        assert result["response_status"] == "finished"

    async def test_send_message_requires_conversation_id(self) -> None:
        """Test that --conversation-send requires a conversation ID."""
        from openhands_langgraph.cli import _send_conversation_message

        args = MagicMock()
        args.conversation_send = None
        args.prompt = "Hello"

        with pytest.raises(RuntimeError, match="requires a CONVERSATION_ID"):
            await _send_conversation_message(args)

    async def test_send_message_requires_prompt(self) -> None:
        """Test that --conversation-send requires a message (prompt)."""
        from openhands_langgraph.cli import _send_conversation_message

        args = MagicMock()
        args.conversation_send = "test-conv-id"
        args.prompt = None

        with pytest.raises(RuntimeError, match="requires a message text"):
            await _send_conversation_message(args)


class TestCLIParser:
    """Tests for CLI argument parsing."""

    def test_conversation_list_flag(self) -> None:
        """Test --conversation-list flag parsing."""
        from openhands_langgraph.cli import build_parser

        parser = build_parser()
        args = parser.parse_args([
            "--endpoint", "http://test.local:3000",
            "--conversation-list",
        ])
        assert args.conversation_list is True
        assert args.conversation_send is None
        assert args.prompt is None

    def test_conversation_list_json_flag(self) -> None:
        """Test --conversation-list with --json flag."""
        from openhands_langgraph.cli import build_parser

        parser = build_parser()
        args = parser.parse_args([
            "--endpoint", "http://test.local:3000",
            "--conversation-list",
            "--json",
        ])
        assert args.conversation_list is True
        assert args.output_json_conv is True

    def test_conversation_send_flag(self) -> None:
        """Test --conversation-send flag parsing."""
        from openhands_langgraph.cli import build_parser

        parser = build_parser()
        args = parser.parse_args([
            "--endpoint", "http://test.local:3000",
            "--conversation-send", "abc123",
            "--prompt", "Hello!",
        ])
        assert args.conversation_send == "abc123"
        assert args.prompt == "Hello!"
        assert args.wait is False

    def test_conversation_send_with_wait(self) -> None:
        """Test --conversation-send with --wait flag."""
        from openhands_langgraph.cli import build_parser

        parser = build_parser()
        args = parser.parse_args([
            "--endpoint", "http://test.local:3000",
            "--conversation-send", "abc123",
            "--prompt", "Hello!",
            "--wait",
        ])
        assert args.conversation_send == "abc123"
        assert args.wait is True

    def test_workflow_mode_requires_prompt(self) -> None:
        """Test that workflow modes without --prompt raise error."""
        from openhands_langgraph.cli import build_parser, _amain

        parser = build_parser()
        args = parser.parse_args([
            "--endpoint", "http://test.local:3000",
        ])
        assert args.prompt is None
        assert args.conversation_list is False
        assert args.conversation_send is None

        # _amain should raise RuntimeError for workflow modes without prompt
        with pytest.raises(RuntimeError, match="required for workflow modes"):
            import asyncio
            asyncio.run(_amain(args))

    def test_conversation_list_bypasses_prompt_requirement(self) -> None:
        """Test that --conversation-list doesn't require --prompt."""
        from openhands_langgraph.cli import build_parser

        parser = build_parser()
        args = parser.parse_args([
            "--endpoint", "http://test.local:3000",
            "--conversation-list",
        ])
        assert args.conversation_list is True
        assert args.prompt is None  # Should not require prompt


class TestMainOutput:
    """Tests for main() output formatting."""

    async def test_main_conversation_list_human_output(self) -> None:
        """Test human-readable output for conversation-list."""
        from openhands_langgraph.cli import main
        import io
        from contextlib import redirect_stdout

        mock_result = {
            "conversations": [
                {
                    "id": "conv-1",
                    "title": "Test",
                    "llm_model": "openai/coder",
                    "status": "finished",
                }
            ],
            "total": 1,
        }

        with patch("openhands_langgraph.cli.asyncio.run", return_value=mock_result):
            with patch("sys.argv", ["openhands-graph-run", "--endpoint", "http://test.local:3000", "--conversation-list"]):
                f = io.StringIO()
                with redirect_stdout(f):
                    with pytest.raises(SystemExit) as exc_info:
                        main()
                assert exc_info.value.code == 0
                output = f.getvalue()
                assert "Found 1 conversation" in output
                assert "conv-1" in output
                assert "Test" in output
                assert "openai/coder" in output

    async def test_main_conversation_list_json_output(self) -> None:
        """Test JSON output for conversation-list with --json."""
        from openhands_langgraph.cli import main
        import io
        from contextlib import redirect_stdout

        mock_result = {
            "conversations": [
                {
                    "id": "conv-1",
                    "title": "Test",
                    "llm_model": "openai/coder",
                    "status": "finished",
                }
            ],
            "total": 1,
        }

        with patch("openhands_langgraph.cli.asyncio.run", return_value=mock_result):
            with patch("sys.argv", ["openhands-graph-run", "--endpoint", "http://test.local:3000", "--conversation-list", "--json"]):
                f = io.StringIO()
                with redirect_stdout(f):
                    with pytest.raises(SystemExit) as exc_info:
                        main()
                assert exc_info.value.code == 0
                output = f.getvalue()
                data = json.loads(output)
                assert data["total"] == 1
                assert data["conversations"][0]["id"] == "conv-1"

    async def test_main_conversation_send_human_output(self) -> None:
        """Test human-readable output for conversation-send."""
        from openhands_langgraph.cli import main
        import io
        from contextlib import redirect_stdout

        mock_result = {
            "conversation_id": "conv-1",
            "llm_model": "openai/coder",
            "waited": True,
            "response": "Assistant response text",
        }

        with patch("openhands_langgraph.cli.asyncio.run", return_value=mock_result):
            with patch("sys.argv", ["openhands-graph-run", "--endpoint", "http://test.local:3000", "--conversation-send", "conv-1", "--prompt", "Hello", "--wait"]):
                f = io.StringIO()
                with redirect_stdout(f):
                    with pytest.raises(SystemExit) as exc_info:
                        main()
                assert exc_info.value.code == 0
                output = f.getvalue()
                assert "conv-1" in output
                assert "openai/coder" in output
                assert "Assistant response text" in output

    async def test_main_conversation_send_json_output(self) -> None:
        """Test JSON output for conversation-send with --json."""
        from openhands_langgraph.cli import main
        import io
        from contextlib import redirect_stdout

        mock_result = {
            "conversation_id": "conv-1",
            "llm_model": "openai/coder",
            "waited": True,
            "response": "Assistant response text",
        }

        with patch("openhands_langgraph.cli.asyncio.run", return_value=mock_result):
            with patch("sys.argv", ["openhands-graph-run", "--endpoint", "http://test.local:3000", "--conversation-send", "conv-1", "--prompt", "Hello", "--json"]):
                f = io.StringIO()
                with redirect_stdout(f):
                    with pytest.raises(SystemExit) as exc_info:
                        main()
                assert exc_info.value.code == 0
                output = f.getvalue()
                data = json.loads(output)
                assert data["conversation_id"] == "conv-1"
                assert data["response"] == "Assistant response text"
