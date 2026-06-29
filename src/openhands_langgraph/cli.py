from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

from openhands import OpenHandsInstance, OpenHandsRoleRunner
from openhands.client import OpenHandsClient

from .graph import build_development_graph, build_single_role_graph, build_team_lead_graph
from .ui import make_workflow_ui

_COLOR = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
}


def _c(text: str, color: str, *, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{_COLOR.get(color, '')}{text}{_COLOR['reset']}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _duration_text(seconds: Any) -> str:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "unknown"
    if value < 1:
        return f"{value * 1000:.0f}ms"
    if value < 60:
        return f"{value:.1f}s"
    minutes, rest = divmod(value, 60)
    if minutes < 60:
        return f"{int(minutes)}m {rest:.0f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m {rest:.0f}s"


def _count_role_actions(role_results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for role_result in role_results:
        summary = role_result.get("summary") or {}
        action = str(role_result.get("summary_action") or summary.get("action") or "UNKNOWN").upper()
        counts[action] = counts.get(action, 0) + 1
    return counts


def _load_role_model_config(config_path: str | None) -> dict[str, str] | None:
    """Load per-role model configuration from YAML file.

    Discovery order:
    1. Explicit path from config_path argument
    2. OPENHANDS_CONFIG environment variable
    3. ./.openhands-role-models.yaml
    4. ./config.yaml

    Returns the 'roles' dict from the YAML file, or None if not found/invalid.
    """
    import logging

    paths_to_try: list[str] = []

    if config_path:
        paths_to_try.append(config_path)
    else:
        env_path = os.environ.get("OPENHANDS_CONFIG")
        if env_path:
            paths_to_try.append(env_path)
        paths_to_try.extend([".openhands-role-models.yaml", "config.yaml"])

    try:
        import yaml
    except ImportError:
        yaml = None  # type: ignore[assignment]

    for path in paths_to_try:
        try:
            if not os.path.isfile(path):
                continue
            if yaml is None:
                logging.warning("PyYAML is not installed; cannot load role model config from %s", path)
                continue

            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict) and "roles" in data:
                roles = data["roles"]
                if isinstance(roles, dict) and roles:
                    logging.info("Loaded role model config from %s", path)
                    return {k: str(v) for k, v in roles.items() if v}
                elif roles:
                    logging.warning("YAML config 'roles' key is empty or not a dict: %s", path)
                    return None
        except Exception as exc:  # noqa: BLE001
            logging.warning("Failed to load YAML config %s: %s", path, exc)
            return None

    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openhands-graph-run",
        description="Run LangGraph workflows backed by OpenHands.",
    )
    parser.add_argument("--workflow", choices=["single-role", "development", "team-lead"], default="single-role")
    parser.add_argument("--endpoint", required=True, help="OpenHands endpoint, for example http://127.0.0.1:3000")
    parser.add_argument("--api-key", default=os.environ.get("OPENHANDS_API_KEY"))
    parser.add_argument("--model", default=None, help="Optional OpenHands llm_model")
    parser.add_argument("--config", default=None, help="Path to YAML config file with per-role model overrides")
    parser.add_argument("--team-lead-base-url", default=os.environ.get("TEAM_LEAD_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_BASE_URL") or os.environ.get("LITELLM_BASE_URL"), help="OpenAI-compatible base URL for tool-less Team Lead decisions, e.g. http://127.0.0.1:4000/v1")
    parser.add_argument("--team-lead-api-key", default=os.environ.get("TEAM_LEAD_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY") or os.environ.get("LITELLM_API_KEY"), help="API key for Team Lead LLM endpoint")
    parser.add_argument("--team-lead-model", default=os.environ.get("TEAM_LEAD_MODEL"), help="Model for tool-less Team Lead. Defaults to --model")
    parser.add_argument("--team-lead-timeout", type=float, default=120.0, help="Team Lead direct LLM timeout. Default: 120")
    parser.add_argument("--team-lead-max-attempts", type=int, default=3, help="Team Lead JSON decision attempts. Default: 3")
    parser.add_argument("--prompt", help="Task prompt (required for workflow modes)")
    parser.add_argument("--role", default="role", help="Role name for single-role workflow. Default: role")
    parser.add_argument("--role-instance", default=None, help="Optional role instance id, e.g. architect_A")
    parser.add_argument("--repository", default=None, help="Optional selected_repository")
    parser.add_argument("--branch", default=None, help="Optional selected_branch")
    parser.add_argument("--git-provider", default=None, help="Optional git_provider")
    parser.add_argument("--max-fix-iterations", type=int, default=2, help="Development workflow coder retry limit. Default: 2")
    parser.add_argument("--max-team-lead-steps", type=int, default=12, help="Team Lead workflow step limit. Default: 12")
    parser.add_argument("--summary-max-attempts", type=int, default=3, help="Summary attempts for graph CLI. Default: 3; use 0 for unlimited")
    parser.add_argument("--start-poll-interval", type=float, default=5.0)
    parser.add_argument("--websocket-retry-seconds", type=float, default=240.0)
    parser.add_argument("--terminal-grace-seconds", type=float, default=15.0)
    parser.add_argument("--show-events", action="store_true")
    parser.add_argument("--raw-websocket", action="store_true")
    parser.add_argument("--output-json", action="store_true", help="Print full JSON graph state instead of readable colored summary")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors in readable output")
    parser.add_argument("--no-graph-trace", action="store_true", help="Do not print per-role input/result trace")
    parser.add_argument("--ui", choices=["auto", "rich", "plain", "off"], default="auto", help="Human output UI mode. Default: auto (Rich dashboard when available).")
    parser.add_argument("--ui-prompt-chars", type=int, default=6000, help="Max compact prompt-context chars shown in rich UI. Full prompts are hidden. Default: 6000")
    parser.add_argument("--ui-answer-chars", type=int, default=8000, help="Max answer chars shown in rich UI panels. Default: 8000")

    # Conversation-list mode
    parser.add_argument("--conversation-list", action="store_true", help="List conversations and their metadata")
    parser.add_argument("--json", action="store_true", dest="output_json_conv", help="Output conversation list as JSON")

    # Conversation-send mode
    parser.add_argument("--conversation-send", metavar="CONVERSATION_ID", help="Send a message to an existing conversation")
    parser.add_argument("--wait", action="store_true", help="Wait for the assistant response when sending a message")

    return parser


async def _list_conversations(args: argparse.Namespace) -> dict[str, Any]:
    """List conversations and their metadata via GET /api/v1/app-conversations/search."""
    client = OpenHandsClient(args.endpoint, api_key=args.api_key)
    all_conversations: list[dict[str, Any]] = []
    page_id: str | None = None
    limit = 100
    has_more = True

    while has_more:
        search_result = await client.search_app_conversations(limit=limit, page_id=page_id)
        conversations: list[dict[str, Any]] = []

        if isinstance(search_result, list):
            conversations = search_result
        elif isinstance(search_result, dict):
            # The search endpoint may return {"items": [...], "next_page_id": "..."}
            # or just a list directly.
            items = search_result.get("items") or search_result.get("conversations") or []
            if isinstance(items, list):
                conversations = items
            else:
                conversations = [search_result]

        all_conversations.extend(conversations)

        # Check for pagination
        if isinstance(search_result, dict):
            page_id = search_result.get("next_page_id") or search_result.get("page_id")
            has_more = bool(page_id)
        else:
            has_more = False

    # Build output records with metadata
    records = []
    for conv in all_conversations:
        record: dict[str, Any] = {
            "id": conv.get("id") or conv.get("conversation_id") or "",
            "title": conv.get("title") or "",
            "llm_model": conv.get("llm_model") or "",
            "status": conv.get("execution_status") or conv.get("status") or "",
            "sandbox_id": conv.get("sandbox_id") or "",
            "created_at": conv.get("created_at") or conv.get("created") or "",
            "updated_at": conv.get("updated_at") or conv.get("updated") or "",
        }
        records.append(record)

    return {"conversations": records, "total": len(records)}


async def _send_conversation_message(args: argparse.Namespace) -> dict[str, Any]:
    """Send a message to an existing conversation and optionally wait for response."""
    conversation_id = args.conversation_send
    message_text = args.prompt  # prompt is used as the message text

    if not conversation_id:
        raise RuntimeError("--conversation-send requires a CONVERSATION_ID argument")
    if not message_text:
        raise RuntimeError("--conversation-send requires a message text (use --prompt)")

    instance = OpenHandsInstance(args.endpoint, api_key=args.api_key, default_model=args.model)

    # Attach to the existing conversation
    conversation = await instance.attach_conversation(conversation_id, refresh=True, verbose=True)

    # Get the raw conversation data to extract llm_model
    raw_conv = await instance.client.get_app_conversation(conversation_id)
    llm_model = ""
    if isinstance(raw_conv, dict):
        llm_model = raw_conv.get("llm_model") or ""
    elif isinstance(raw_conv, list) and raw_conv:
        llm_model = raw_conv[0].get("llm_model") if isinstance(raw_conv[0], dict) else ""

    # Send the message
    result = await instance.client.send_message_to_existing_conversation(conversation, message_text, run=True)

    output: dict[str, Any] = {
        "conversation_id": conversation_id,
        "message_sent": message_text,
        "send_result": result,
        "llm_model": llm_model,
        "waited": args.wait,
    }

    if args.wait:
        # Wait for the assistant response by streaming events
        print(f"[wait] streaming events for conversation {conversation_id}...", file=sys.stderr)
        final_text: str | None = None
        final_status: str | None = None
        terminal_seen = False
        terminal_deadline: float | None = None
        saw_agent_activity = False
        saw_running_status = False

        event_iter = instance.client.stream_v1_events(
            conversation,
            raw_websocket=args.raw_websocket,
            open_timeout=20.0,
            retry_seconds=args.websocket_retry_seconds,
        )

        try:
            while True:
                timeout: float | None = None
                if terminal_seen and not final_text and terminal_deadline is not None:
                    timeout = max(0.0, terminal_deadline - asyncio.get_running_loop().time())
                try:
                    if timeout is None:
                        event = await anext(event_iter)
                    else:
                        event = await asyncio.wait_for(anext(event_iter), timeout=timeout)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    break
                except Exception as exc:  # noqa: BLE001
                    print(f"[warn] websocket error: {exc}", file=sys.stderr)
                    break

                kind = str(event.get("kind") or "")
                if kind == "ActionEvent" or kind == "ObservationEvent":
                    saw_agent_activity = True

                # Extract assistant text
                content_list = event.get("llm_message", {}).get("content", [])
                for item in content_list:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        if text.strip():
                            final_text = text

                status = str(event.get("value") or "")
                if event.get("key") == "execution_status":
                    if status == "running":
                        saw_running_status = True
                    if status in {"finished", "error", "cancelled"}:
                        final_status = status
                        if final_text:
                            break
                        terminal_seen = True
                        terminal_deadline = asyncio.get_running_loop().time() + max(0.0, args.terminal_grace_seconds)
                        continue

                # Print events if requested
                if args.show_events:
                    print(json.dumps(event, ensure_ascii=False), flush=True)

        finally:
            await event_iter.aclose()

        # Fallback: try REST if no text was captured
        if not final_text:
            try:
                fallback = await instance.client.fetch_final_text_fallback(conversation)
                if fallback.strip():
                    final_text = fallback
            except Exception:  # noqa: BLE001
                pass

        output["response"] = final_text.strip() if final_text and final_text.strip() else ""
        output["response_status"] = final_status
        output["waited"] = True

    return output


async def _amain(args: argparse.Namespace) -> dict[str, Any]:
    # Handle conversation-list mode
    if args.conversation_list:
        result = await _list_conversations(args)
        if args.output_json_conv:
            return {"conversations": result["conversations"], "total": result["total"]}
        return result

    # Handle conversation-send mode
    if args.conversation_send:
        return await _send_conversation_message(args)

    # Original workflow modes require --prompt
    if not args.prompt:
        raise RuntimeError("--prompt is required for workflow modes (single-role, development, team-lead)")

    instance = OpenHandsInstance(args.endpoint, api_key=args.api_key, default_model=args.model)
    runner = OpenHandsRoleRunner(instance, summary_max_attempts=args.summary_max_attempts)

    # Load per-role model configuration from YAML file.
    role_models = _load_role_model_config(args.config)

    graph = build_development_graph() if args.workflow == "development" else build_team_lead_graph() if args.workflow == "team-lead" else build_single_role_graph()
    state: dict[str, Any] = {
        "workflow": args.workflow,
        "user_task": args.prompt,
        "role": args.role,
        "role_instance": args.role_instance,
        "model": args.model,
        "repository": args.repository,
        "branch": args.branch,
        "git_provider": args.git_provider,
        "current_iteration": 0,
        "max_fix_iterations": args.max_fix_iterations,
        "team_lead_steps": 0,
        "max_team_lead_steps": args.max_team_lead_steps,
        "role_sessions": {},
        "role_run_options": {
            "start_poll_interval": args.start_poll_interval,
            "websocket_retry_seconds": args.websocket_retry_seconds,
            "terminal_grace_seconds": args.terminal_grace_seconds,
            "show_events": args.show_events,
            "raw_websocket": args.raw_websocket,
        },
    }
    if role_models:
        state["role_models"] = role_models
    started_at = _utc_now_iso()
    started_monotonic = time.monotonic()
    ui = None
    if not args.output_json and args.ui not in {"plain", "off"}:
        ui = make_workflow_ui(args.ui, no_color=args.no_color)
        # Allow CLI flags to tune compact-context/answer panel sizes without exposing Rich internals.
        if hasattr(ui, "prompt_max_chars"):
            ui.prompt_max_chars = args.ui_prompt_chars
        if hasattr(ui, "answer_max_chars"):
            ui.answer_max_chars = args.ui_answer_chars
        ui.start()
    try:
        result = await graph.ainvoke(
            state,
            config={
                "configurable": {
                    "openhands_runner": runner,
                    "team_lead_base_url": args.team_lead_base_url,
                    "team_lead_api_key": args.team_lead_api_key,
                    "team_lead_model": args.team_lead_model or args.model,
                    "team_lead_timeout": args.team_lead_timeout,
                    "team_lead_max_attempts": args.team_lead_max_attempts,
                    "openhands_graph_trace": (not args.no_graph_trace and not args.output_json and ui is None),
                    "openhands_graph_color": not args.no_color,
                    "openhands_workflow_ui": ui,
                }
            },
        )
    except BaseException:
        if ui is not None:
            try:
                ui.stop()
            except Exception:
                pass
        raise
    finished_at = _utc_now_iso()
    total_duration_seconds = round(max(0.0, time.monotonic() - started_monotonic), 3)
    role_results = result.get("role_results") or []
    total_summary_attempts = sum(int((rr.get("metrics") or {}).get("summary_attempt_count") or rr.get("summary_attempt_count") or 0) for rr in role_results)
    result["workflow_metrics"] = {
        "workflow": args.workflow,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": total_duration_seconds,
        "role_count": len(role_results),
        "summary_attempt_count": total_summary_attempts,
        "error_count": len(result.get("errors") or []),
        "current_iteration": result.get("current_iteration", state.get("current_iteration", 0)),
        "max_fix_iterations": state.get("max_fix_iterations"),
        "team_lead_steps": result.get("team_lead_steps", state.get("team_lead_steps", 0)),
        "max_team_lead_steps": state.get("max_team_lead_steps"),
        "actions": _count_role_actions(role_results),
    }
    if ui is not None:
        try:
            ui.final_result(result)
        finally:
            ui.stop()
    return result


def _short(text: Any, limit: int = 320) -> str:
    value = str(text or "").replace("\n", " ").strip()
    if len(value) > limit:
        return value[: limit - 3] + "..."
    return value


def _print_human_result(result: dict[str, Any], *, color: bool) -> None:
    status = result.get("final_status") or "unknown"
    status_color = "green" if status == "completed" else "yellow" if status in {"needs_fix", "needs_human_review"} else "red"
    print()
    print(_c("═" * 72, "dim", enabled=color))
    print(_c(f"Workflow result: {status}", status_color, enabled=color))
    print(_c("═" * 72, "dim", enabled=color))

    metrics = result.get("workflow_metrics") or {}
    role_results = result.get("role_results") or []

    print(_c("Metrics:", "bold", enabled=color))
    print(f"  total duration: {_duration_text(metrics.get('duration_seconds'))}")
    print(f"  roles executed: {metrics.get('role_count', len(role_results))}")
    print(f"  summary attempts: {metrics.get('summary_attempt_count', 'unknown')}")
    print(f"  fix iterations: {metrics.get('current_iteration', result.get('current_iteration', 0))}/{metrics.get('max_fix_iterations', result.get('max_fix_iterations', 'unknown'))}")
    if metrics.get("max_team_lead_steps") is not None:
        print(f"  team lead steps: {metrics.get('team_lead_steps', result.get('team_lead_steps', 0))}/{metrics.get('max_team_lead_steps')}")
    actions = metrics.get("actions") or {}
    if actions:
        action_text = ", ".join(f"{name}={count}" for name, count in sorted(actions.items()))
        print(f"  actions: {action_text}")
    if metrics.get("started_at") and metrics.get("finished_at"):
        print(f"  window: {metrics.get('started_at')} → {metrics.get('finished_at')}")

    if role_results:
        print()
        print(_c("Per-role results:", "bold", enabled=color))
    for idx, role_result in enumerate(role_results, start=1):
        summary = role_result.get("summary") or {}
        role = role_result.get("role") or "role"
        action = role_result.get("summary_action") or summary.get("action") or ""
        risk = role_result.get("risk_level") or summary.get("risk_level") or ""
        blocking = role_result.get("blocking") if role_result.get("blocking") is not None else summary.get("blocking")
        ok = role_result.get("ok")
        role_metrics = role_result.get("metrics") or {}
        marker_color = "green" if ok else "red"
        print(_c(f"{idx}. {role}", marker_color, enabled=color))
        print(f"   action: {action or 'unknown'}")
        print(f"   risk: {risk or 'unknown'}")
        print(f"   blocking: {blocking}")
        print(f"   duration: {_duration_text(role_metrics.get('duration_seconds'))}")
        print(f"   summary attempts: {role_metrics.get('summary_attempt_count', role_result.get('summary_attempt_count', 'unknown'))}")
        if role_metrics.get("answer_chars") is not None:
            print(f"   answer chars: {role_metrics.get('answer_chars')}")
        if role_result.get("conversation_id"):
            print(f"   conversation: {role_result.get('conversation_id')}")
        if summary.get("summary"):
            print(f"   summary: {_short(summary.get('summary'))}")

    if result.get("errors"):
        print(_c("Errors:", "red", enabled=color))
        for error in result.get("errors") or []:
            print(f"  - {error}")

    if result.get("final_answer"):
        print()
        print(_c("Final answer:", "bold", enabled=color))
        print(_short(result.get("final_answer"), 1000))


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(_amain(args))
    except RuntimeError as exc:
        print(f"openhands-graph-run: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        raise SystemExit(130)

    # Handle output for conversation-list mode
    if args.conversation_list:
        if args.output_json_conv or args.output_json:
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            conversations = result.get("conversations") or []
            total = result.get("total", len(conversations))
            print(f"Found {total} conversation(s):\n")
            for conv in conversations:
                conv_id = conv.get("id", "")
                title = conv.get("title", "")
                model = conv.get("llm_model", "")
                status = conv.get("status", "")
                print(f"  ID:       {conv_id}")
                print(f"  Title:    {title}")
                print(f"  Model:    {model}")
                print(f"  Status:   {status}")
                print()
        raise SystemExit(0)

    # Handle output for conversation-send mode
    if args.conversation_send:
        if args.output_json or args.output_json_conv:
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"Message sent to conversation {result.get('conversation_id', '')}")
            if result.get("llm_model"):
                print(f"LLM Model: {result.get('llm_model')}")
            if result.get("waited"):
                response = result.get("response", "")
                if response:
                    print(f"\nResponse:\n{response}")
                else:
                    print("\n[no response captured]")
        raise SystemExit(0)

    # Original workflow modes output
    if args.output_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human_result(result, color=not args.no_color)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
