from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .client import OpenHandsError, load_json_object, run_prompt_and_watch


GIT_PROVIDER_CHOICES = (
    "github",
    "gitlab",
    "bitbucket",
    "bitbucket_data_center",
    "forgejo",
    "azure_devops",
    "enterprise_sso",
)

TRIGGER_CHOICES = (
    "resolver",
    "gui",
    "suggested_task",
    "openhands_api",
    "slack",
    "microagent_management",
    "jira",
    "jira_dc",
    "linear",
    "bitbucket",
    "automation",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openhands-watch",
        description=(
            "Create an OpenHands V1 app conversation with only the fields explicitly "
            "provided by the user, then wait for completion and print the final answer."
        ),
    )
    parser.add_argument(
        "--endpoint",
        required=True,
        help="OpenHands endpoint, for example: http://127.0.0.1:3000",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENHANDS_API_KEY"),
        help="Optional API key. Defaults to OPENHANDS_API_KEY env var.",
    )

    # Core request fields. None of these is sent unless the flag is present.
    parser.add_argument(
        "--model",
        dest="llm_model",
        default=None,
        help="Optional llm_model field for POST /api/v1/app-conversations, e.g. openai/coder.",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help=(
            "Optional text prompt. When provided, creates initial_message={content:[{type:text,text:<prompt>}]}. "
            "If omitted, provide initial_message via --initial-message-json/--payload-json/--payload-file."
        ),
    )
    parser.add_argument("--sandbox-id", default=None, help="Optional sandbox_id: reuse/start against an existing sandbox id.")
    parser.add_argument("--conversation-id", default=None, help="Optional conversation_id UUID.")
    parser.add_argument("--system-message-suffix", default=None, help="Optional system_message_suffix.")
    parser.add_argument("--repository", dest="selected_repository", default=None, help="Optional selected_repository, e.g. owner/repo.")
    parser.add_argument("--branch", dest="selected_branch", default=None, help="Optional selected_branch.")
    parser.add_argument("--git-provider", choices=GIT_PROVIDER_CHOICES, default=None, help="Optional git_provider.")
    parser.add_argument("--title", default=None, help="Optional title.")
    parser.add_argument("--trigger", choices=TRIGGER_CHOICES, default=None, help="Optional trigger enum value.")
    parser.add_argument(
        "--pr-number",
        action="append",
        type=int,
        default=None,
        help="Optional pr_number entry. May be repeated, e.g. --pr-number 12 --pr-number 15.",
    )
    parser.add_argument("--parent-conversation-id", default=None, help="Optional parent_conversation_id UUID.")
    parser.add_argument("--agent-type", choices=("default", "plan"), default=None, help="Optional agent_type.")

    public_group = parser.add_mutually_exclusive_group()
    public_group.add_argument("--public", dest="public", action="store_true", default=None, help="Set public=true.")
    public_group.add_argument("--private", dest="public", action="store_false", help="Set public=false.")

    # Complex JSON fields.
    parser.add_argument(
        "--initial-message-json",
        default=None,
        metavar="JSON",
        help="Full JSON value for initial_message. Overrides --prompt when both are provided.",
    )
    parser.add_argument(
        "--initial-message-file",
        default=None,
        metavar="PATH",
        help="Read full JSON value for initial_message from file. Overrides --prompt and --initial-message-json.",
    )
    parser.add_argument(
        "--processors-json",
        default=None,
        metavar="JSON",
        help="JSON array for processors.",
    )
    parser.add_argument(
        "--processors-file",
        default=None,
        metavar="PATH",
        help="Read JSON array for processors from file.",
    )
    parser.add_argument(
        "--suggested-task-json",
        default=None,
        metavar="JSON",
        help="JSON object for suggested_task.",
    )
    parser.add_argument(
        "--suggested-task-file",
        default=None,
        metavar="PATH",
        help="Read JSON object for suggested_task from file.",
    )
    parser.add_argument(
        "--plugin-json",
        action="append",
        default=None,
        metavar="JSON",
        help=(
            "Plugin object to append to plugins. May be repeated. Example: "
            "--plugin-json '{\"source\":\"github:owner/plugin\",\"ref\":\"main\"}'"
        ),
    )
    parser.add_argument(
        "--plugins-json",
        default=None,
        metavar="JSON",
        help="JSON array for plugins. If combined with --plugin-json, entries are appended.",
    )
    parser.add_argument(
        "--plugins-file",
        default=None,
        metavar="PATH",
        help="Read JSON array for plugins from file. If combined with --plugin-json, entries are appended.",
    )
    parser.add_argument(
        "--secret",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="Secret to pass in secrets object. May be repeated. Values are not logged by this CLI.",
    )
    parser.add_argument(
        "--secrets-json",
        default=None,
        metavar="JSON",
        help="JSON object for secrets. Combined with --secret, where --secret wins on duplicate keys.",
    )
    parser.add_argument(
        "--secrets-file",
        default=None,
        metavar="PATH",
        help="Read JSON object for secrets from file. Combined with --secret, where --secret wins on duplicate keys.",
    )

    # Escape hatch for unsupported/new OpenHands fields.
    parser.add_argument(
        "--payload-json",
        default=None,
        metavar="JSON",
        help=(
            "Base JSON object for POST /api/v1/app-conversations. CLI flags are merged on top. "
            "Only fields present in this JSON or explicit flags are sent."
        ),
    )
    parser.add_argument(
        "--payload-file",
        default=None,
        metavar="PATH",
        help="Read base JSON object for POST /api/v1/app-conversations from file. Merged before --payload-json and flags.",
    )
    parser.add_argument(
        "--param-json",
        action="append",
        default=None,
        metavar="FIELD=JSON",
        help=(
            "Set an arbitrary top-level request field to a JSON value. May be repeated. "
            "Example: --param-json 'tags={\"role\":\"scout\"}'"
        ),
    )

    # Output / runtime controls.
    parser.add_argument(
        "--show-events",
        action="store_true",
        help="Show compact event trace while waiting. By default events are hidden and only the final assistant answer is printed.",
    )
    parser.add_argument(
        "--raw-events",
        action="store_true",
        help="Print full JSON event payloads instead of compact human-readable lines. Implies --show-events.",
    )
    parser.add_argument(
        "--debug-events",
        action="store_true",
        help="Print compact trace plus debug state/stat summaries. Implies --show-events and is ignored when --raw-events is used.",
    )
    parser.add_argument(
        "--raw-websocket",
        action="store_true",
        help="Print websocket connection URL to stderr for debugging.",
    )
    parser.add_argument(
        "--print-payload",
        action="store_true",
        help="Print the final app-conversation JSON payload to stderr before sending. Secrets are redacted.",
    )
    parser.add_argument(
        "--no-exit-when-terminal",
        action="store_true",
        help="Keep following the websocket stream even after execution_status reaches a terminal state.",
    )
    parser.add_argument(
        "--start-poll-interval",
        type=float,
        default=5.0,
        help="Polling interval while waiting for the V1 start task to become READY. Default: 5.",
    )
    parser.add_argument(
        "--websocket-open-timeout",
        type=float,
        default=20.0,
        help="Seconds to wait for each websocket handshake before trying the next candidate URL. Default: 20.",
    )
    parser.add_argument(
        "--websocket-retry-seconds",
        type=float,
        default=240.0,
        help=(
            "Total seconds to keep retrying websocket connection during agent-server startup. "
            "Default: 240. Use 0 to fail after one candidate round."
        ),
    )
    parser.add_argument(
        "--terminal-grace-seconds",
        type=float,
        default=15.0,
        help="After terminal execution_status arrives without a final answer, keep reading websocket briefly before REST fallback. Default: 15.",
    )
    parser.add_argument(
        "--rest-terminal-watch",
        action="store_true",
        help=(
            "Also poll REST app-conversation metadata for terminal state. Disabled by default because "
            "some local OpenHands builds can report terminal metadata before the websocket final answer."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        exit_code = asyncio.run(
            run_prompt_and_watch(
                endpoint=args.endpoint,
                api_key=args.api_key,
                show_events=args.show_events,
                raw_events=args.raw_events,
                debug_events=args.debug_events,
                raw_websocket=args.raw_websocket,
                exit_when_terminal=not args.no_exit_when_terminal,
                start_poll_interval=args.start_poll_interval,
                websocket_open_timeout=args.websocket_open_timeout,
                websocket_retry_seconds=args.websocket_retry_seconds,
                terminal_grace_seconds=args.terminal_grace_seconds,
                rest_terminal_watch=args.rest_terminal_watch,
                print_payload=args.print_payload,
                payload_file=args.payload_file,
                payload_json=args.payload_json,
                param_json=args.param_json,
                # Known AppConversationStartRequest fields. All default to None
                # and are therefore omitted unless explicitly provided.
                sandbox_id=args.sandbox_id,
                conversation_id=args.conversation_id,
                prompt=args.prompt,
                llm_model=args.llm_model,
                initial_message_json=args.initial_message_json,
                initial_message_file=args.initial_message_file,
                system_message_suffix=args.system_message_suffix,
                processors_json=args.processors_json,
                processors_file=args.processors_file,
                selected_repository=args.selected_repository,
                selected_branch=args.selected_branch,
                git_provider=args.git_provider,
                suggested_task_json=args.suggested_task_json,
                suggested_task_file=args.suggested_task_file,
                title=args.title,
                trigger=args.trigger,
                pr_number=args.pr_number,
                parent_conversation_id=args.parent_conversation_id,
                agent_type=args.agent_type,
                public=args.public,
                plugins_json=args.plugins_json,
                plugins_file=args.plugins_file,
                plugin_json=args.plugin_json,
                secrets_json=args.secrets_json,
                secrets_file=args.secrets_file,
                secret=args.secret,
            )
        )
    except OpenHandsError as exc:
        print(f"openhands-watch: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        raise SystemExit(130)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
