"""Tests for sandbox listing and messaging commands."""
from __future__ import annotations

import json
import sys
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openhands.client import OpenHandsClient, OpenHandsError

pytestmark = pytest.mark.asyncio


class TestListSandboxes:
    """Test the list_sandboxes client method."""

    async def test_list_sandboxes_returns_list(self) -> None:
        """Test that list_sandboxes returns a list of sandbox dicts."""
        mock_response = [
            {
                "id": "sandbox-1",
                "status": "running",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T01:00:00Z",
                "type": "docker",
            },
            {
                "id": "sandbox-2",
                "status": "stopped",
                "created_at": "2024-01-02T00:00:00Z",
                "updated_at": "2024-01-02T01:00:00Z",
                "type": "docker",
            },
        ]

        client = OpenHandsClient(endpoint="http://test:3000")
        
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await client.list_sandboxes()
            
            assert result == mock_response
            mock_request.assert_called_once_with("GET", "/api/v1/sandboxes/search")

    async def test_list_sandboxes_handles_wrapped_response(self) -> None:
        """Test that list_sandboxes handles wrapped responses."""
        mock_response = {
            "items": [
                {
                    "id": "sandbox-1",
                    "status": "running",
                }
            ]
        }

        client = OpenHandsClient(endpoint="http://test:3000")
        
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await client.list_sandboxes()
            
            assert result == [{"id": "sandbox-1", "status": "running"}]

    async def test_list_sandboxes_handles_single_sandbox(self) -> None:
        """Test that list_sandboxes handles a single sandbox response."""
        mock_response = {
            "id": "sandbox-1",
            "status": "running",
        }

        client = OpenHandsClient(endpoint="http://test:3000")
        
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await client.list_sandboxes()
            
            assert result == [{"id": "sandbox-1", "status": "running"}]

    async def test_list_sandboxes_handles_empty_response(self) -> None:
        """Test that list_sandboxes handles empty responses."""
        client = OpenHandsClient(endpoint="http://test:3000")
        
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = []
            result = await client.list_sandboxes()
            
            assert result == []


class TestSearchConversationsBySandbox:
    """Test the search_conversations_by_sandbox client method."""

    async def test_search_conversations_returns_list(self) -> None:
        """Test that search_conversations_by_sandbox returns conversations."""
        mock_response = [
            {
                "id": "conv-1",
                "sandbox_id": "sandbox-1",
                "status": "running",
            },
            {
                "id": "conv-2",
                "sandbox_id": "sandbox-1",
                "status": "finished",
            },
        ]

        client = OpenHandsClient(endpoint="http://test:3000")
        
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await client.search_conversations_by_sandbox("sandbox-1")
            
            assert len(result) == 2
            assert result[0]["id"] == "conv-1"
            mock_request.assert_called_once_with(
                "GET",
                "/api/v1/app-conversations/search",
                params={"sandbox_id": "sandbox-1"},
            )

    async def test_search_conversations_handles_wrapped_response(self) -> None:
        """Test that search handles wrapped responses."""
        mock_response = {
            "items": [
                {"id": "conv-1", "sandbox_id": "sandbox-1"},
            ]
        }

        client = OpenHandsClient(endpoint="http://test:3000")
        
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await client.search_conversations_by_sandbox("sandbox-1")
            
            assert result == [{"id": "conv-1", "sandbox_id": "sandbox-1"}]


class TestSendToSandbox:
    """Test the send_to_sandbox CLI command."""

    async def test_send_to_sandbox_no_conversations(self) -> None:
        """Test sending to sandbox with no active conversations."""
        from openhands.cli import cmd_send_to_sandbox

        client = OpenHandsClient(endpoint="http://test:3000")
        
        with patch.object(client, "search_conversations_by_sandbox", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            
            with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
                exit_code = await cmd_send_to_sandbox(client, "sandbox-1", "test message")
                
                assert exit_code == 1
                assert "No active conversations found" in mock_stderr.getvalue()

    async def test_send_to_sandbox_success(self) -> None:
        """Test successful message sending to sandbox."""
        from openhands.cli import cmd_send_to_sandbox
        from openhands.models import AppConversationStart

        client = OpenHandsClient(endpoint="http://test:3000")
        
        mock_conversations = [
            {
                "id": "conv-1",
                "sandbox_id": "sandbox-1",
                "status": "running",
            }
        ]

        with patch.object(client, "search_conversations_by_sandbox", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = mock_conversations
            
            with patch.object(client, "send_message_to_existing_conversation", new_callable=AsyncMock) as mock_send:
                mock_send.return_value = None
                
                with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
                    exit_code = await cmd_send_to_sandbox(client, "sandbox-1", "test message")
                    
                    assert exit_code == 0
                    mock_send.assert_called_once()
                    # Verify that AppConversationStart object was passed
                    call_args = mock_send.call_args
                    conversation_obj = call_args[0][0]
                    assert isinstance(conversation_obj, AppConversationStart)
                    assert conversation_obj.conversation_id == "conv-1"

    async def test_send_to_sandbox_with_conversation_url(self) -> None:
        """Test that send_to_sandbox creates proper AppConversationStart with conversation_url."""
        from openhands.cli import cmd_send_to_sandbox
        from openhands.models import AppConversationStart

        client = OpenHandsClient(endpoint="http://test:3000")
        
        mock_conversations = [
            {
                "id": "conv-1",
                "sandbox_id": "sandbox-1",
                "status": "running",
            }
        ]

        with patch.object(client, "search_conversations_by_sandbox", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = mock_conversations
            
            with patch.object(client, "send_message_to_existing_conversation", new_callable=AsyncMock) as mock_send:
                mock_send.return_value = None
                
                exit_code = await cmd_send_to_sandbox(client, "sandbox-1", "test message")
                
                assert exit_code == 0
                # Verify that AppConversationStart object was passed with conversation_url attribute
                call_args = mock_send.call_args
                conversation_obj = call_args[0][0]
                assert isinstance(conversation_obj, AppConversationStart)
                assert hasattr(conversation_obj, 'conversation_url')
                assert hasattr(conversation_obj, 'agent_server_url')
                assert hasattr(conversation_obj, 'conversation_id')


class TestCLIIntegration:
    """Integration tests for CLI sandbox commands."""

    async def test_list_sandbox_cli_table_format(self) -> None:
        """Test that --list-sandbox outputs table format."""
        from openhands.cli import cmd_list_sandboxes
        from openhands.client import OpenHandsClient

        client = OpenHandsClient(endpoint="http://test:3000")
        
        mock_sandboxes = [
            {
                "id": "sandbox-1",
                "status": "running",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T01:00:00Z",
                "type": "docker",
            },
        ]

        with patch.object(client, "list_sandboxes", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = mock_sandboxes
            
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
                    exit_code = await cmd_list_sandboxes(client, json_output=False)
                    
                    assert exit_code == 0
                    output = mock_stdout.getvalue()
                    assert "sandbox-1" in output
                    assert "running" in output
                    assert "Total: 1 sandbox(es)" in mock_stderr.getvalue()

    async def test_list_sandbox_cli_json_format(self) -> None:
        """Test that --list-sandbox --json outputs JSON format."""
        from openhands.cli import cmd_list_sandboxes
        from openhands.client import OpenHandsClient

        client = OpenHandsClient(endpoint="http://test:3000")
        
        mock_sandboxes = [
            {
                "id": "sandbox-1",
                "status": "running",
            },
        ]

        with patch.object(client, "list_sandboxes", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = mock_sandboxes
            
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                exit_code = await cmd_list_sandboxes(client, json_output=True)
                
                assert exit_code == 0
                output = mock_stdout.getvalue()
                parsed = json.loads(output)
                assert parsed[0]["id"] == "sandbox-1"

    async def test_list_sandbox_cli_with_model(self) -> None:
        """Test that --list-sandbox shows model name from conversation."""
        from openhands.cli import cmd_list_sandboxes
        from openhands.client import OpenHandsClient

        client = OpenHandsClient(endpoint="http://test:3000")
        
        mock_sandboxes = [
            {
                "id": "sandbox-1",
                "status": "running",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T01:00:00Z",
                "type": "docker",
            },
        ]
        
        mock_conversations = [
            {
                "id": "conv-1",
                "sandbox_id": "sandbox-1",
                "status": "running",
                "llm_model": "openai/coder",
            }
        ]

        with patch.object(client, "list_sandboxes", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = mock_sandboxes
            with patch.object(client, "search_conversations_by_sandbox", new_callable=AsyncMock) as mock_search:
                mock_search.return_value = mock_conversations
                
                with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                    with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
                        exit_code = await cmd_list_sandboxes(client, json_output=False)
                        
                        assert exit_code == 0
                        output = mock_stdout.getvalue()
                        assert "sandbox-1" in output
                        # Check that model was enriched in sandbox data
                        assert mock_sandboxes[0].get("llm_model") == "openai/coder"

    async def test_list_sandbox_empty(self) -> None:
        """Test listing when no sandboxes exist."""
        from openhands.cli import cmd_list_sandboxes
        from openhands.client import OpenHandsClient

        client = OpenHandsClient(endpoint="http://test:3000")

        with patch.object(client, "list_sandboxes", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = []
            
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
                    exit_code = await cmd_list_sandboxes(client, json_output=False)
                    
                    assert exit_code == 0
                    output = mock_stdout.getvalue()
                    assert "No sandboxes found" in output
                    assert "Total: 0 sandbox(es)" in mock_stderr.getvalue()
