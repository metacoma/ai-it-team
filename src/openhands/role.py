from __future__ import annotations

from typing import Any

from .instance import OpenHandsInstance
from .runner import OpenHandsRoleRunner, RoleRunResult
from .summary import (
    DEFAULT_SUMMARY_INSTRUCTIONS,
    SummaryAttempt,
    build_summary_prompt,
    parse_json_strict,
)


async def run_role_with_summary(
    *,
    endpoint: str,
    api_key: str | None = None,
    summary_model: str | None = None,
    summary_instructions: str = DEFAULT_SUMMARY_INSTRUCTIONS,
    summary_max_attempts: int = 0,
    summary_show_attempts: bool = False,
    show_events: bool = False,
    raw_events: bool = False,
    debug_events: bool = False,
    raw_websocket: bool = False,
    start_poll_interval: float = 5.0,
    websocket_open_timeout: float = 20.0,
    websocket_retry_seconds: float = 240.0,
    terminal_grace_seconds: float = 15.0,
    rest_terminal_watch: bool = False,
    print_payload: bool = False,
    # Main conversation explicit-only payload fields.
    payload_file: str | None = None,
    payload_json: str | None = None,
    param_json: list[str] | None = None,
    sandbox_id: str | None = None,
    conversation_id: str | None = None,
    prompt: str | None = None,
    llm_model: str | None = None,
    initial_message_json: str | None = None,
    initial_message_file: str | None = None,
    system_message_suffix: str | None = None,
    processors_json: str | None = None,
    processors_file: str | None = None,
    selected_repository: str | None = None,
    selected_branch: str | None = None,
    git_provider: str | None = None,
    suggested_task_json: str | None = None,
    suggested_task_file: str | None = None,
    title: str | None = None,
    trigger: str | None = None,
    pr_number: list[int] | None = None,
    parent_conversation_id: str | None = None,
    agent_type: str | None = None,
    public: bool | None = None,
    plugins_json: str | None = None,
    plugins_file: str | None = None,
    plugin_json: list[str] | None = None,
    secrets_json: str | None = None,
    secrets_file: str | None = None,
    secret: list[str] | None = None,
) -> RoleRunResult:
    """Backward-compatible function wrapper around OpenHandsRoleRunner."""
    if summary_model and summary_model != llm_model and summary_show_attempts:
        import sys

        print(
            "[summary] --summary-model is ignored for same-conversation summary; "
            "OpenHands cannot switch llm_model after the conversation is already running",
            file=sys.stderr,
        )

    instance = OpenHandsInstance(endpoint=endpoint, api_key=api_key, default_model=None)
    runner = OpenHandsRoleRunner(
        instance,
        summary_instructions=summary_instructions,
        summary_max_attempts=summary_max_attempts,
    )
    return await runner.run_role(
        role="role",
        role_instance=None,
        prompt=prompt,
        model=llm_model,
        repository=selected_repository,
        branch=selected_branch,
        git_provider=git_provider,
        sandbox_id=sandbox_id,
        conversation_id=conversation_id,
        title=title,
        summary_instructions=summary_instructions,
        summary_max_attempts=summary_max_attempts,
        summary_show_attempts=summary_show_attempts,
        show_events=show_events,
        raw_events=raw_events,
        debug_events=debug_events,
        raw_websocket=raw_websocket,
        start_poll_interval=start_poll_interval,
        websocket_open_timeout=websocket_open_timeout,
        websocket_retry_seconds=websocket_retry_seconds,
        terminal_grace_seconds=terminal_grace_seconds,
        payload_file=payload_file,
        payload_json=payload_json,
        param_json=param_json,
        initial_message_json=initial_message_json,
        initial_message_file=initial_message_file,
        system_message_suffix=system_message_suffix,
        processors_json=processors_json,
        processors_file=processors_file,
        suggested_task_json=suggested_task_json,
        suggested_task_file=suggested_task_file,
        trigger=trigger,
        pr_number=pr_number,
        parent_conversation_id=parent_conversation_id,
        agent_type=agent_type,
        public=public,
        plugins_json=plugins_json,
        plugins_file=plugins_file,
        plugin_json=plugin_json,
        secrets_json=secrets_json,
        secrets_file=secrets_file,
        secret=secret,
        print_payload=print_payload,
        rest_terminal_watch=rest_terminal_watch,
    )


__all__ = [
    "DEFAULT_SUMMARY_INSTRUCTIONS",
    "SummaryAttempt",
    "RoleRunResult",
    "build_summary_prompt",
    "parse_json_strict",
    "run_role_with_summary",
]
