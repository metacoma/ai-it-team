from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Any, Callable

from .client import (
    AppConversationStart,
    JsonDict,
    OpenHandsClient,
    OpenHandsRunResult,
    collect_started_conversation,
    run_followup_message_and_collect,
)


@dataclass(frozen=True)
class OpenHandsConversation:
    """One concrete OpenHands conversation/sandbox runtime.

    The object is intentionally lightweight and can be passed around by SDK
    users while LangGraph state stores only its serializable ids/metadata.
    """

    instance: Any
    start: AppConversationStart

    @property
    def conversation_id(self) -> str:
        return self.start.conversation_id

    @property
    def sandbox_id(self) -> str | None:
        return self.start.sandbox_id

    @property
    def agent_server_url(self) -> str | None:
        return self.start.agent_server_url

    @property
    def conversation_url(self) -> str | None:
        return self.start.conversation_url

    @property
    def session_api_key(self) -> str | None:
        return self.start.session_api_key

    @property
    def client(self) -> OpenHandsClient:
        return self.instance.client

    async def stream_events(
        self,
        *,
        raw_websocket: bool = False,
        open_timeout: float = 20.0,
        retry_seconds: float = 240.0,
    ) -> AsyncIterator[JsonDict]:
        async for event in self.client.stream_v1_events(
            self.start,
            raw_websocket=raw_websocket,
            open_timeout=open_timeout,
            retry_seconds=retry_seconds,
        ):
            yield event

    async def wait_finished(
        self,
        *,
        known_event_ids: set[str] | frozenset[str] | None = None,
        show_events: bool = False,
        raw_events: bool = False,
        debug_events: bool = False,
        raw_websocket: bool = False,
        event_callback: Callable[[JsonDict], None] | None = None,
        exit_when_terminal: bool = True,
        websocket_open_timeout: float = 20.0,
        websocket_retry_seconds: float = 240.0,
        terminal_grace_seconds: float = 15.0,
    ) -> OpenHandsRunResult:
        return await collect_started_conversation(
            endpoint=self.instance.endpoint,
            api_key=self.instance.api_key,
            conversation=self.start,
            known_event_ids=known_event_ids,
            show_events=show_events,
            raw_events=raw_events,
            debug_events=debug_events,
            raw_websocket=raw_websocket,
            event_callback=event_callback,
            exit_when_terminal=exit_when_terminal,
            websocket_open_timeout=websocket_open_timeout,
            websocket_retry_seconds=websocket_retry_seconds,
            terminal_grace_seconds=terminal_grace_seconds,
        )

    async def send_message(
        self,
        prompt: str,
        *,
        run: bool = True,
        known_event_ids: set[str] | frozenset[str] | None = None,
        show_events: bool = False,
        raw_events: bool = False,
        debug_events: bool = False,
        raw_websocket: bool = False,
        event_callback: Callable[[JsonDict], None] | None = None,
        exit_when_terminal: bool = True,
        websocket_open_timeout: float = 20.0,
        websocket_retry_seconds: float = 240.0,
        terminal_grace_seconds: float = 15.0,
    ) -> OpenHandsRunResult:
        # Keep the public flag for callers, but the current OpenHands role flow
        # expects run=True. If run=False is ever needed, call the lower-level
        # client directly and stream_events() manually.
        if run is not True:
            await self.client.send_message_to_existing_conversation(self.start, prompt, run=False)
            return OpenHandsRunResult(
                text="",
                status=None,
                conversation_id=self.conversation_id,
                start=self.start,
                seen_event_ids=frozenset(known_event_ids or set()),
            )
        return await run_followup_message_and_collect(
            endpoint=self.instance.endpoint,
            api_key=self.instance.api_key,
            conversation=self.start,
            known_event_ids=known_event_ids,
            show_events=show_events,
            raw_events=raw_events,
            debug_events=debug_events,
            raw_websocket=raw_websocket,
            event_callback=event_callback,
            exit_when_terminal=exit_when_terminal,
            websocket_open_timeout=websocket_open_timeout,
            websocket_retry_seconds=websocket_retry_seconds,
            terminal_grace_seconds=terminal_grace_seconds,
            prompt=prompt,
        )
