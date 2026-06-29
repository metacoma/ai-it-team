"""Tests for sandbox reuse (--reuse flag) functionality."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from openhands_langgraph.nodes import _find_sandbox_for_model, _resolve_role_model
from openhands_langgraph.state import OpenHandsGraphState


pytestmark = pytest.mark.asyncio


class TestFindSandboxForModel:
    """Test the _find_sandbox_for_model helper."""

    async def test_returns_none_when_model_is_none(self) -> None:
        """When model is None, return None without API calls."""
        client = AsyncMock()
        cache: dict = {}
        result = await _find_sandbox_for_model(client, None, cache)
        assert result is None
        client.search_app_conversations.assert_not_called()

    async def test_returns_cached_sandbox_when_valid(self) -> None:
        """When model is in cache and sandbox is RUNNING, return cached id."""
        client = AsyncMock()
        client.search_sandboxes = AsyncMock(return_value={
            "items": [
                {"id": "sb-1", "status": "RUNNING"},
            ]
        })
        cache = {"openai/coder": "sb-1"}
        result = await _find_sandbox_for_model(client, "openai/coder", cache)
        assert result == "sb-1"
        client.search_app_conversations.assert_not_called()

    async def test_returns_cached_sandbox_when_paused(self) -> None:
        """When model is in cache and sandbox is PAUSED, return cached id."""
        client = AsyncMock()
        client.search_sandboxes = AsyncMock(return_value={
            "items": [
                {"id": "sb-1", "status": "PAUSED"},
            ]
        })
        cache = {"openai/coder": "sb-1"}
        result = await _find_sandbox_for_model(client, "openai/coder", cache)
        assert result == "sb-1"

    async def test_updates_invalid_cached_sandbox(self) -> None:
        """When cached sandbox is ERROR, update cache with new found sandbox."""
        client = AsyncMock()
        client.search_sandboxes = AsyncMock(return_value={
            "items": [
                {"id": "sb-1", "status": "ERROR"},
            ]
        })
        client.search_app_conversations = AsyncMock(return_value={
            "items": [
                {"llm_model": "openai/coder", "sandbox_id": "sb-2"},
            ],
            "next_page_id": None,
        })
        cache = {"openai/coder": "sb-1"}
        result = await _find_sandbox_for_model(client, "openai/coder", cache)
        assert result == "sb-2"
        assert cache["openai/coder"] == "sb-2"  # cache updated to new sandbox

    async def test_finds_sandbox_by_model_via_conversations(self) -> None:
        """When not cached, paginate conversations to find matching model."""
        client = AsyncMock()
        client.search_sandboxes = AsyncMock(return_value={
            "items": [
                {"id": "sb-2", "status": "RUNNING"},
            ]
        })
        client.search_app_conversations = AsyncMock(return_value={
            "items": [
                {"llm_model": "openai/coder", "sandbox_id": "sb-2"},
            ],
            "next_page_id": None,
        })
        cache: dict = {}
        result = await _find_sandbox_for_model(client, "openai/coder", cache)
        assert result == "sb-2"
        assert cache["openai/coder"] == "sb-2"

    async def test_returns_none_when_no_matching_conversation(self) -> None:
        """When no conversation matches the model, return None."""
        client = AsyncMock()
        client.search_sandboxes = AsyncMock(return_value={"items": []})
        client.search_app_conversations = AsyncMock(return_value={
            "items": [
                {"llm_model": "other/model", "sandbox_id": "sb-3"},
            ],
            "next_page_id": None,
        })
        cache: dict = {}
        result = await _find_sandbox_for_model(client, "openai/coder", cache)
        assert result is None
        assert not cache  # cache remains empty

    async def test_handles_api_error_gracefully(self) -> None:
        """When API calls fail, return None without crashing."""
        client = AsyncMock()
        client.search_sandboxes = AsyncMock(side_effect=Exception("API error"))
        client.search_app_conversations = AsyncMock(side_effect=Exception("API error"))
        cache: dict = {}
        result = await _find_sandbox_for_model(client, "openai/coder", cache)
        assert result is None

    async def test_caches_found_sandbox(self) -> None:
        """When a sandbox is found, it is cached for subsequent lookups."""
        client = AsyncMock()
        client.search_sandboxes = AsyncMock(return_value={
            "items": [
                {"id": "sb-1", "status": "RUNNING"},
            ]
        })
        client.search_app_conversations = AsyncMock(return_value={
            "items": [
                {"llm_model": "openai/coder", "sandbox_id": "sb-1"},
            ],
            "next_page_id": None,
        })
        cache: dict = {}
        # First call: finds and caches
        result1 = await _find_sandbox_for_model(client, "openai/coder", cache)
        assert result1 == "sb-1"
        assert cache["openai/coder"] == "sb-1"
        # Second call: uses cache (no conversation search)
        client.search_app_conversations.reset_mock()
        result2 = await _find_sandbox_for_model(client, "openai/coder", cache)
        assert result2 == "sb-1"
        client.search_app_conversations.assert_not_called()


class TestResolveRoleModel:
    """Test the _resolve_role_model helper."""

    def test_returns_role_model_from_role_models(self) -> None:
        """When role_models has entry for role, return it."""
        state: OpenHandsGraphState = {
            "role_models": {"scout": "custom/model"},
            "model": "default/model",
        }
        result = _resolve_role_model("scout", state)
        assert result == "custom/model"

    def test_falls_back_to_global_model(self) -> None:
        """When role_models has no entry for role, return global model."""
        state: OpenHandsGraphState = {
            "role_models": {"architect": "arch/model"},
            "model": "default/model",
        }
        result = _resolve_role_model("scout", state)
        assert result == "default/model"

    def test_returns_none_when_no_model(self) -> None:
        """When no models configured, return None."""
        state: OpenHandsGraphState = {}
        result = _resolve_role_model("scout", state)
        assert result is None

    def test_skips_empty_role_model(self) -> None:
        """When role model is empty string, fall back to global."""
        state: OpenHandsGraphState = {
            "role_models": {"scout": ""},
            "model": "default/model",
        }
        result = _resolve_role_model("scout", state)
        assert result == "default/model"


class TestCLIReuseFlag:
    """Test that --reuse flag is parsed correctly."""

    def test_reuse_flag_defaults_to_false(self) -> None:
        """Without --reuse, the flag should be False."""
        from openhands_langgraph.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["--endpoint", "http://localhost:3000", "--prompt", "test"])
        assert args.reuse is False

    def test_reuse_flag_set_when_present(self) -> None:
        """With --reuse, the flag should be True."""
        from openhands_langgraph.cli import build_parser
        parser = build_parser()
        args = parser.parse_args([
            "--endpoint", "http://localhost:3000",
            "--prompt", "test",
            "--reuse",
        ])
        assert args.reuse is True

    def test_reuse_flag_in_help(self) -> None:
        """--reuse should appear in help text."""
        from openhands_langgraph.cli import build_parser
        import io
        from contextlib import redirect_stdout
        parser = build_parser()
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                parser.parse_args(["--help"])
            except SystemExit:
                pass
        help_text = f.getvalue()
        assert "--reuse" in help_text
        assert "Reuse existing sandbox" in help_text


class TestStateFields:
    """Test that state fields exist for sandbox reuse."""

    def test_state_accepts_reuse_sandbox(self) -> None:
        """OpenHandsGraphState should accept reuse_sandbox field."""
        from openhands_langgraph.state import OpenHandsGraphState
        state: OpenHandsGraphState = {
            "user_task": "test",
            "prompt": "test",
            "role": "scout",
            "reuse_sandbox": True,
            "sandbox_cache": {},
        }
        assert state["reuse_sandbox"] is True
        assert state["sandbox_cache"] == {}

    def test_state_accepts_sandbox_cache(self) -> None:
        """OpenHandsGraphState should accept sandbox_cache field."""
        from openhands_langgraph.state import OpenHandsGraphState
        state: OpenHandsGraphState = {
            "user_task": "test",
            "prompt": "test",
            "role": "scout",
            "reuse_sandbox": False,
            "sandbox_cache": {"openai/coder": "sb-1"},
        }
        assert state["sandbox_cache"]["openai/coder"] == "sb-1"
