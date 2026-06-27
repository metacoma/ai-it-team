from __future__ import annotations

import asyncio
import sys
from typing import Any, Callable

from .client import AppConversationStart, OpenHandsError, OpenHandsRunResult
from .conversation import OpenHandsConversation
from .instance import OpenHandsInstance
from .models import JsonDict, RoleRunResult, RoleRunSpec, RoleSummary, SummaryAttempt
from .summary import (
    DEFAULT_SUMMARY_INSTRUCTIONS,
    build_summary_prompt,
    parse_role_summary,
)


class OpenHandsRoleRunner:
    """Role abstraction: task answer + same-conversation JSON summary."""

    def __init__(
        self,
        instance: OpenHandsInstance,
        *,
        summary_instructions: str = DEFAULT_SUMMARY_INSTRUCTIONS,
        summary_max_attempts: int = 0,
    ) -> None:
        self.instance = instance
        self.summary_instructions = summary_instructions
        self.summary_max_attempts = summary_max_attempts

    async def run_role(
        self,
        *,
        role: str = "role",
        role_instance: str | None = None,
        prompt: str | None = None,
        model: str | None = None,
        repository: str | None = None,
        branch: str | None = None,
        git_provider: str | None = None,
        sandbox_id: str | None = None,
        conversation_id: str | None = None,
        conversation_start: AppConversationStart | None = None,
        known_event_ids: set[str] | frozenset[str] | None = None,
        title: str | None = None,
        extra_payload: JsonDict | None = None,
        summary_instructions: str | None = None,
        summary_max_attempts: int | None = None,
        summary_show_attempts: bool = False,
        show_events: bool = False,
        raw_events: bool = False,
        debug_events: bool = False,
        raw_websocket: bool = False,
        event_callback: Callable[[JsonDict], None] | None = None,
        start_poll_interval: float = 5.0,
        websocket_open_timeout: float = 20.0,
        websocket_retry_seconds: float = 240.0,
        terminal_grace_seconds: float = 15.0,
        print_payload: bool = False,
        rest_terminal_watch: bool = False,
        **conversation_params: Any,
    ) -> RoleRunResult:
        if conversation_start is not None:
            # Persistent role conversation: do not create a new app conversation
            # or sandbox. Send the role prompt as a follow-up to the existing
            # role_instance conversation and ignore replayed events by id.
            conversation = OpenHandsConversation(instance=self.instance, start=conversation_start)
            answer_run = await conversation.send_message(
                prompt or "",
                run=True,
                known_event_ids=known_event_ids,
                show_events=show_events,
                raw_events=raw_events,
                debug_events=debug_events,
                raw_websocket=raw_websocket,
                event_callback=event_callback,
                websocket_open_timeout=websocket_open_timeout,
                websocket_retry_seconds=websocket_retry_seconds,
                terminal_grace_seconds=terminal_grace_seconds,
            )
        else:
            conversation = await self.instance.create_conversation(
                prompt=prompt,
                model=model,
                repository=repository,
                branch=branch,
                git_provider=git_provider,
                sandbox_id=sandbox_id,
                conversation_id=conversation_id,
                title=title,
                extra_payload=extra_payload,
                start_poll_interval=start_poll_interval,
                verbose_start=bool(show_events or raw_events or debug_events or raw_websocket),
                print_payload=print_payload,
                **conversation_params,
            )
            answer_run = await conversation.wait_finished(
                known_event_ids=known_event_ids,
                show_events=show_events,
                raw_events=raw_events,
                debug_events=debug_events,
                raw_websocket=raw_websocket,
                event_callback=event_callback,
                websocket_open_timeout=websocket_open_timeout,
                websocket_retry_seconds=websocket_retry_seconds,
                terminal_grace_seconds=terminal_grace_seconds,
            )

        answer = answer_run.text
        if not answer.strip():
            raise OpenHandsError("main OpenHands run finished without an assistant answer; cannot summarize")

        instructions = summary_instructions if summary_instructions is not None else self.summary_instructions
        max_attempts = self.summary_max_attempts if summary_max_attempts is None else summary_max_attempts
        attempts: list[SummaryAttempt] = []
        previous_text: str | None = None
        previous_error: str | None = None
        known_event_ids: set[str] = set(answer_run.seen_event_ids)
        attempt = 1

        while True:
            if max_attempts > 0 and attempt > max_attempts:
                raise OpenHandsError(
                    f"summary did not become valid JSON after {max_attempts} attempts; "
                    f"last error: {previous_error or 'unknown'}"
                )

            summary_prompt = build_summary_prompt(
                answer=answer,
                instructions=instructions,
                previous_text=previous_text,
                previous_error=previous_error,
            )
            if summary_show_attempts:
                print(f"[summary] attempt {attempt}", file=sys.stderr)

            summary_run = await conversation.send_message(
                summary_prompt,
                run=True,
                known_event_ids=known_event_ids,
                show_events=show_events,
                raw_events=raw_events,
                debug_events=debug_events,
                raw_websocket=raw_websocket,
                event_callback=event_callback,
                websocket_open_timeout=websocket_open_timeout,
                websocket_retry_seconds=websocket_retry_seconds,
                terminal_grace_seconds=terminal_grace_seconds,
            )
            summary_text = summary_run.text
            try:
                parsed = parse_role_summary(summary_text)
            except OpenHandsError as exc:
                previous_text = summary_text
                previous_error = str(exc)
                attempts.append(
                    SummaryAttempt(
                        attempt=attempt,
                        text=summary_text,
                        parsed_json=None,
                        error=previous_error,
                        conversation_id=summary_run.conversation_id,
                    )
                )
                known_event_ids = set(summary_run.seen_event_ids)
                if summary_show_attempts:
                    print(f"[summary] invalid JSON: {previous_error}", file=sys.stderr)
                attempt += 1
                continue

            attempts.append(
                SummaryAttempt(
                    attempt=attempt,
                    text=summary_text,
                    parsed_json=parsed,
                    error=None,
                    conversation_id=summary_run.conversation_id,
                )
            )
            return RoleRunResult(
                role=role,
                role_instance=role_instance,
                answer=answer,
                summary_text=summary_text.strip(),
                summary_json=parsed,
                answer_run=answer_run,
                summary_attempts=attempts,
                conversation=conversation,
                seen_event_ids=frozenset(summary_run.seen_event_ids),
            )

    async def run_roles_parallel(
        self,
        specs: list[RoleRunSpec],
        *,
        max_concurrency: int | None = None,
        fail_fast: bool = False,
        **run_kwargs: Any,
    ) -> list[RoleRunResult]:
        semaphore = asyncio.Semaphore(max_concurrency or len(specs) or 1)

        async def run_one(spec: RoleRunSpec) -> RoleRunResult:
            async with semaphore:
                try:
                    return await self.run_role(
                        role=spec.role,
                        role_instance=spec.role_instance,
                        prompt=spec.prompt,
                        model=spec.model,
                        repository=spec.repository,
                        branch=spec.branch,
                        git_provider=spec.git_provider,
                        sandbox_id=spec.sandbox_id,
                        conversation_id=spec.conversation_id,
                        title=spec.title,
                        extra_payload=spec.extra_payload,
                        **spec.conversation_params,
                        **run_kwargs,
                    )
                except Exception as exc:
                    if fail_fast:
                        raise
                    failed_start = AppConversationStart(
                        conversation_id=spec.conversation_id or "",
                        status="failed",
                    )
                    empty_run = OpenHandsRunResult(
                        text="",
                        status="failed",
                        conversation_id=spec.conversation_id or "",
                        start=failed_start,
                    )
                    return RoleRunResult(
                        role=spec.role,
                        role_instance=spec.role_instance,
                        answer="",
                        summary_text="",
                        summary_json=RoleSummary(
                            valid=False,
                            status="failed",
                            summary=str(exc),
                            action=None,
                            risk_level=None,
                            blocking=True,
                            blocking_summary=[str(exc)],
                        ),
                        answer_run=empty_run,
                        summary_attempts=[],
                        conversation=None,
                        error=str(exc),
                    )

        return await asyncio.gather(*(run_one(spec) for spec in specs))
