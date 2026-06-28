from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from aiohttp import web

JsonDict = dict[str, Any]


def _message_event(event_id: str, text: str, *, source: str = "agent") -> JsonDict:
    role = "assistant" if source == "agent" else "user"
    return {
        "id": event_id,
        "kind": "MessageEvent",
        "source": source,
        "llm_message": {
            "role": role,
            "content": [{"type": "text", "text": text}],
        },
    }


def _status_event(event_id: str, status: str) -> JsonDict:
    return {
        "id": event_id,
        "kind": "ConversationStateUpdateEvent",
        "source": "environment",
        "key": "execution_status",
        "value": status,
    }


def main_run_events(answer: str = "main answer") -> list[JsonDict]:
    return [
        _status_event("main-running", "running"),
        {
            "id": "main-action-1",
            "kind": "ActionEvent",
            "source": "agent",
            "tool_name": "think",
            "action": {"kind": "ThinkAction", "thought": "working"},
        },
        _message_event("main-answer", answer),
        _status_event("main-finished", "finished"),
    ]


def summary_run_events(text: str, *, prefix: str = "summary") -> list[JsonDict]:
    return [
        _status_event(f"{prefix}-running", "running"),
        _message_event(f"{prefix}-answer", text),
        _status_event(f"{prefix}-finished", "finished"),
    ]


@dataclass
class FakeOpenHandsServer:
    """In-process OpenHands-like app server + agent server mock.

    The mock intentionally exposes both REST and WebSocket endpoints on one
    aiohttp server so tests exercise the real HTTP/WebSocket code paths:

    * POST /api/v1/app-conversations
    * GET  /api/v1/app-conversations/start-tasks
    * GET  /api/v1/app-conversations
    * GET  /api/v1/sandboxes/search
    * GET  /api/v1/app-conversations/search
    * POST /api/conversations/{conversation_id}/events
    * GET  /sockets/events/{conversation_id}
    """

    main_events: list[JsonDict] = field(default_factory=main_run_events)
    summary_event_batches: list[list[JsonDict]] = field(
        default_factory=lambda: [summary_run_events('{"valid": true, "status": "completed", "summary": "ok", "action": null, "risk_level": null, "blocking": false, "blocking_summary": []}')]
    )
    conversation_id: str = "conv-1"
    task_id: str = "task-1"
    app_runner: web.AppRunner | None = None
    site: web.TCPSite | None = None
    endpoint: str = ""
    created_payloads: list[JsonDict] = field(default_factory=list)
    patched_payloads: list[JsonDict] = field(default_factory=list)
    followup_payloads: list[JsonDict] = field(default_factory=list)
    websocket_connections: int = 0
    title: str | None = None
    sandboxes: list[JsonDict] = field(default_factory=list)
    sandbox_conversations: list[JsonDict] = field(default_factory=list)

    async def start(self) -> "FakeOpenHandsServer":
        app = web.Application()
        app.router.add_post("/api/v1/app-conversations", self.handle_create_app_conversation)
        app.router.add_patch("/api/v1/app-conversations/{conversation_id}", self.handle_patch_app_conversation)
        app.router.add_get("/api/v1/app-conversations/start-tasks", self.handle_start_tasks)
        app.router.add_get("/api/v1/app-conversations", self.handle_get_app_conversation)
        app.router.add_get("/api/v1/sandboxes/search", self.handle_list_sandboxes)
        app.router.add_get("/api/v1/app-conversations/search", self.handle_search_conversations)
        app.router.add_route("*", "/api/conversations/{conversation_id}/events", self.handle_conversation_events)
        app.router.add_get("/api/conversations/{conversation_id}/messages", self.handle_conversation_messages)
        app.router.add_get("/api/conversations/{conversation_id}/state", self.handle_conversation_state)
        app.router.add_get("/sockets/events/{conversation_id}", self.handle_websocket)
        self.app_runner = web.AppRunner(app)
        await self.app_runner.setup()
        self.site = web.TCPSite(self.app_runner, "127.0.0.1", 0)
        await self.site.start()
        sockets = self.site._server.sockets  # type: ignore[union-attr, protected-access]
        port = sockets[0].getsockname()[1]
        self.endpoint = f"http://127.0.0.1:{port}"
        return self

    async def stop(self) -> None:
        if self.app_runner:
            await self.app_runner.cleanup()

    def conversation_record(self) -> JsonDict:
        return {
            "id": self.conversation_id,
            "conversation_url": f"{self.endpoint}/api/conversations/{self.conversation_id}",
            "agent_server_url": self.endpoint,
            "session_api_key": "fake-session-key",
            "execution_status": "running",
            "title": self.title or f"Conversation {self.conversation_id[:5]}",
        }

    async def handle_create_app_conversation(self, request: web.Request) -> web.Response:
        payload = await request.json()
        self.created_payloads.append(payload)
        return web.json_response({"id": self.task_id, "status": "WORKING"})

    async def handle_patch_app_conversation(self, request: web.Request) -> web.Response:
        payload = await request.json()
        self.patched_payloads.append(payload)
        if "title" in payload:
            self.title = str(payload["title"])
        record = self.conversation_record()
        record.update(payload)
        return web.json_response(record)

    async def handle_start_tasks(self, request: web.Request) -> web.Response:
        return web.json_response([
            {
                "id": self.task_id,
                "status": "READY",
                "app_conversation_id": self.conversation_id,
                "conversation_url": f"{self.endpoint}/api/conversations/{self.conversation_id}",
                "agent_server_url": self.endpoint,
                "session_api_key": "fake-session-key",
            }
        ])

    async def handle_get_app_conversation(self, request: web.Request) -> web.Response:
        return web.json_response([self.conversation_record()])

    async def handle_list_sandboxes(self, request: web.Request) -> web.Response:
        """Handle GET /api/v1/sandboxes/search"""
        return web.json_response(self.sandboxes)

    async def handle_search_conversations(self, request: web.Request) -> web.Response:
        """Handle GET /api/v1/app-conversations/search?sandbox_id={id}"""
        sandbox_id = request.query.get("sandbox_id")
        if sandbox_id:
            # Filter conversations for this sandbox
            filtered = [
                conv for conv in self.sandbox_conversations
                if conv.get("sandbox_id") == sandbox_id
            ]
            return web.json_response(filtered)
        return web.json_response(self.sandbox_conversations)

    async def handle_conversation_events(self, request: web.Request) -> web.Response:
        if request.method == "POST":
            payload = await request.json()
            self.followup_payloads.append(payload)
            return web.json_response({"success": True})
        history = self.main_events[:]
        for batch in self.summary_event_batches[: len(self.followup_payloads)]:
            history.extend(batch)
        return web.json_response(history)

    async def handle_conversation_messages(self, request: web.Request) -> web.Response:
        messages = [event for event in self.main_events if event.get("kind") == "MessageEvent"]
        for batch in self.summary_event_batches[: len(self.followup_payloads)]:
            messages.extend(event for event in batch if event.get("kind") == "MessageEvent")
        return web.json_response(messages)

    async def handle_conversation_state(self, request: web.Request) -> web.Response:
        return web.json_response({"events": self.main_events})

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.websocket_connections += 1

        # First connection: main run. Follow-up connections replay main events
        # plus exactly the latest summary batch. The client ignores known event
        # ids, so this mirrors OpenHands resend_all=true behavior.
        events = self.main_events[:]
        if self.followup_payloads:
            batch_idx = min(len(self.followup_payloads), len(self.summary_event_batches)) - 1
            events.extend(self.summary_event_batches[batch_idx])

        for event in events:
            await ws.send_str(json.dumps(event))
            await asyncio.sleep(0)
        await ws.close()
        return ws


@pytest.fixture
async def fake_openhands_server() -> FakeOpenHandsServer:
    server = await FakeOpenHandsServer().start()
    try:
        yield server
    finally:
        await server.stop()


@pytest.fixture
async def fake_openhands_server_factory():
    servers: list[FakeOpenHandsServer] = []

    async def factory(**kwargs: Any) -> FakeOpenHandsServer:
        server = await FakeOpenHandsServer(**kwargs).start()
        servers.append(server)
        return server

    try:
        yield factory
    finally:
        for server in servers:
            await server.stop()
