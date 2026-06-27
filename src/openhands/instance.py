from __future__ import annotations

from typing import Any

from .client import (
    JsonDict,
    OpenHandsClient,
    OpenHandsRunResult,
    build_app_conversation_payload,
    redact_secrets,
    run_conversation_and_collect,
)
from .conversation import OpenHandsConversation


class OpenHandsInstance:
    """SDK facade for one OpenHands app-server endpoint.

    It owns endpoint/auth/default model configuration and exposes higher-level
    conversation creation without leaking REST/WebSocket details to orchestrators
    such as LangGraph.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        api_key: str | None = None,
        default_model: str | None = None,
        default_timeout: float = 60.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.default_timeout = default_timeout
        self.client = OpenHandsClient(self.endpoint, api_key=api_key, timeout=default_timeout)

    async def create_conversation(
        self,
        *,
        payload: JsonDict | None = None,
        prompt: str | None = None,
        model: str | None = None,
        repository: str | None = None,
        branch: str | None = None,
        git_provider: str | None = None,
        sandbox_id: str | None = None,
        conversation_id: str | None = None,
        title: str | None = None,
        extra_payload: JsonDict | None = None,
        start_poll_interval: float = 5.0,
        max_start_attempts: int = 120,
        verbose_start: bool = False,
        print_payload: bool = False,
        **conversation_params: Any,
    ) -> OpenHandsConversation:
        """Create an OpenHands conversation with explicit-only payload semantics."""
        if payload is not None:
            final_payload = dict(payload)
        else:
            base_payload = dict(extra_payload or {})
            if base_payload:
                # Reuse the same validation/merge path as the CLI without adding
                # fields that the caller did not specify.
                import json

                conversation_params.setdefault("payload_json", json.dumps(base_payload))
            final_payload = build_app_conversation_payload(
                prompt=prompt,
                llm_model=model if model is not None else self.default_model,
                selected_repository=repository,
                selected_branch=branch,
                git_provider=git_provider,
                sandbox_id=sandbox_id,
                conversation_id=conversation_id,
                title=title,
                **conversation_params,
            )
        if print_payload:
            import json, sys

            print(json.dumps(redact_secrets(final_payload), ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)

        start = await self.client.start_app_conversation(
            payload=final_payload,
            poll_interval=start_poll_interval,
            max_start_attempts=max_start_attempts,
            verbose_start=verbose_start,
        )
        return OpenHandsConversation(instance=self, start=start)


    async def attach_conversation(
        self,
        conversation_id: str,
        *,
        sandbox_id: str | None = None,
        agent_server_url: str | None = None,
        conversation_url: str | None = None,
        session_api_key: str | None = None,
        refresh: bool = True,
        verbose: bool = False,
    ) -> OpenHandsConversation:
        """Attach to an existing OpenHands conversation without creating a sandbox.

        This is used by orchestrators that keep one persistent conversation per
        role instance. The workspace/filesystem may be shared across role
        containers, while each role keeps its own chat history.
        """
        from .client import AppConversationStart

        start = AppConversationStart(
            conversation_id=conversation_id,
            sandbox_id=sandbox_id,
            agent_server_url=agent_server_url,
            conversation_url=conversation_url,
            session_api_key=session_api_key,
        )
        if refresh:
            start = await self.client._refresh_app_conversation_start_metadata(start, verbose=verbose)
        return OpenHandsConversation(instance=self, start=start)

    async def run(
        self,
        *,
        prompt: str | None = None,
        model: str | None = None,
        repository: str | None = None,
        branch: str | None = None,
        git_provider: str | None = None,
        **kwargs: Any,
    ) -> OpenHandsRunResult:
        """Compatibility convenience: create one conversation and return its answer."""
        return await run_conversation_and_collect(
            endpoint=self.endpoint,
            api_key=self.api_key,
            prompt=prompt,
            llm_model=model if model is not None else self.default_model,
            selected_repository=repository,
            selected_branch=branch,
            git_provider=git_provider,
            **kwargs,
        )
