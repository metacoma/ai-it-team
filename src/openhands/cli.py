from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

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

    # Sandbox management commands.
    sandbox_group = parser.add_mutually_exclusive_group()
    sandbox_group.add_argument(
        "--list-sandbox",
        action="store_true",
        help="List all OpenHands sandboxes in a table format.",
    )
    sandbox_group.add_argument(
        "--send-to-sandbox",
        nargs=2,
        metavar=("SANDBOX_ID", "MESSAGE"),
        help="Send a message to an active sandbox. Requires sandbox-id and message argument.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=False,
        help="Output in JSON format (used with --list-sandbox).",
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


def _format_sandbox_table(sandboxes: list[dict]) -> str:
    """Format sandbox list as a Rich table."""
    from io import StringIO
    
    output = StringIO()
    console = Console(file=output, force_terminal=True)
    table = Table(show_header=True, header_style="bold magenta", show_lines=True)
    
    # Add columns for common sandbox fields
    table.add_column("ID", style="cyan", min_width=36)
    table.add_column("Status", style="green")
    table.add_column("Created At", style="yellow")
    table.add_column("Updated At", style="yellow")
    table.add_column("Type", style="blue")
    table.add_column("Model", style="magenta")
    table.add_column("Error", style="red")
    
    for sb in sandboxes:
        # Extract common fields with safe defaults
        sb_id = str(sb.get("id") or "N/A")
        status = str(sb.get("status") or "unknown")
        created_at = str(sb.get("created_at") or sb.get("createdAt") or "N/A")
        updated_at = str(sb.get("updated_at") or sb.get("updatedAt") or "N/A")
        sb_type = str(sb.get("type") or sb.get("sandbox_type") or "N/A")
        model = str(sb.get("llm_model") or sb.get("model") or "N/A")
        error = str(sb.get("error") or sb.get("error_message") or "")
        
        # Truncate long IDs for display
        if len(sb_id) > 40:
            sb_id = sb_id[:37] + "..."
        
        table.add_row(sb_id, status, created_at, updated_at, sb_type, model, error)
    
    console.print(table)
    return output.getvalue()


async def cmd_list_sandboxes(client: "OpenHandsClient", json_output: bool) -> int:
    """List all sandboxes, either as table or JSON."""
    try:
        sandboxes = await client.list_sandboxes(json_output=json_output)
    except OpenHandsError as exc:
        raise OpenHandsError(f"Failed to list sandboxes: {exc}") from exc
    
    # Enrich sandboxes with model information from conversations
    # Model name is per-conversation, not per-sandbox, so we fetch it from the first conversation
    for sb in sandboxes:
        sb_id = sb.get("id")
        if sb_id:
            try:
                conversations = await client.search_conversations_by_sandbox(sb_id)
                if conversations:
                    # Get the first (most recent) conversation
                    conv = conversations[0]
                    # Check if model is already in sandbox data
                    if "llm_model" not in sb and "model" not in sb:
                        model = conv.get("llm_model") or conv.get("model")
                        if model:
                            sb["llm_model"] = model
            except OpenHandsError:
                # If we can't fetch conversations, just skip model enrichment
                pass
    
    if json_output:
        print(json.dumps(sandboxes, indent=2, default=str))
    else:
        if not sandboxes:
            print("No sandboxes found.")
        else:
            table_str = _format_sandbox_table(sandboxes)
            print(table_str)
    
    print(f"\nTotal: {len(sandboxes)} sandbox(es)", file=sys.stderr)
    return 0


async def cmd_send_to_sandbox(client: "OpenHandsClient", sandbox_id: str, message: str) -> int:
    """Send a message to an active sandbox."""
    print(f"[info] Searching for active conversation in sandbox: {sandbox_id}", file=sys.stderr)
    
    # Step 1: Find conversations for this sandbox
    try:
        conversations = await client.search_conversations_by_sandbox(sandbox_id)
    except OpenHandsError as exc:
        raise OpenHandsError(f"Failed to search conversations for sandbox {sandbox_id}: {exc}") from exc
    
    if not conversations:
        print(
            f"[warn] No active conversations found for sandbox {sandbox_id}. "
            f"Please start a conversation first.",
            file=sys.stderr,
        )
        return 1
    
    # Step 2: Use the first (most recent) conversation
    conversation = conversations[0]
    conversation_id = conversation.get("id") or conversation.get("conversation_id")
    
    if not conversation_id:
        print(
            f"[error] Could not extract conversation ID from sandbox search result: {conversation}",
            file=sys.stderr,
        )
        return 1
    
    print(f"[info] Sending message to conversation {conversation_id}", file=sys.stderr)
    
    # Step 3: Send the message using POST /api/conversations/{id}/events
    try:
        from .client import OpenHandsClient
        from .models import AppConversationStart
        
        # Create a proper AppConversationStart object with all required fields
        conversation_obj = AppConversationStart(
            conversation_id=conversation_id,
            agent_server_url=None,
            conversation_url=None,
        )
        
        # We need to send a message event to the conversation
        # This uses the same endpoint as follow-up messages
        result = await client.send_message_to_existing_conversation(
            conversation_obj,
            message,
            run=True,
        )
        print(f"[success] Message sent successfully to sandbox {sandbox_id}")
        print(f"Conversation ID: {conversation_id}")
        return 0
    except OpenHandsError as exc:
        raise OpenHandsError(f"Failed to send message to sandbox {sandbox_id}: {exc}") from exc


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    
    # Handle sandbox management commands (these don't require --endpoint for listing,
    # but do require it for sending messages)
    if args.list_sandbox:
        if not args.endpoint:
            print("[error] --endpoint is required for --list-sandbox", file=sys.stderr)
            raise SystemExit(1)
        
        try:
            from .client import OpenHandsClient
            client = OpenHandsClient(
                endpoint=args.endpoint,
                api_key=args.api_key,
            )
            exit_code = asyncio.run(cmd_list_sandboxes(client, json_output=args.json_output))
            raise SystemExit(exit_code)
        except OpenHandsError as exc:
            print(f"openhands-watch: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        except KeyboardInterrupt:
            raise SystemExit(130)
    
    if args.send_to_sandbox:
        if not args.endpoint:
            print("[error] --endpoint is required for --send-to-sandbox", file=sys.stderr)
            raise SystemExit(1)
        
        if len(args.send_to_sandbox) != 2:
            print("[error] --send-to-sandbox requires exactly 2 arguments: SANDBOX_ID MESSAGE", file=sys.stderr)
            raise SystemExit(1)
        
        sandbox_id, message = args.send_to_sandbox
        
        try:
            from .client import OpenHandsClient
            client = OpenHandsClient(
                endpoint=args.endpoint,
                api_key=args.api_key,
            )
            exit_code = asyncio.run(cmd_send_to_sandbox(client, sandbox_id, message))
            raise SystemExit(exit_code)
        except OpenHandsError as exc:
            print(f"openhands-watch: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        except KeyboardInterrupt:
            raise SystemExit(130)
    
    # Normal conversation flow
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
