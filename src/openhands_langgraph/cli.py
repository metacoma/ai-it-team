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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openhands-graph-run",
        description="Run LangGraph workflows backed by OpenHands.",
    )
    parser.add_argument("--workflow", choices=["single-role", "development", "team-lead"], default="single-role")
    parser.add_argument("--endpoint", required=True, help="OpenHands endpoint, for example http://127.0.0.1:3000")
    parser.add_argument("--api-key", default=os.environ.get("OPENHANDS_API_KEY"))
    parser.add_argument("--model", default=None, help="Optional OpenHands llm_model")
    parser.add_argument("--team-lead-base-url", default=os.environ.get("TEAM_LEAD_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_BASE_URL") or os.environ.get("LITELLM_BASE_URL"), help="OpenAI-compatible base URL for tool-less Team Lead decisions, e.g. http://127.0.0.1:4000/v1")
    parser.add_argument("--team-lead-api-key", default=os.environ.get("TEAM_LEAD_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY") or os.environ.get("LITELLM_API_KEY"), help="API key for Team Lead LLM endpoint")
    parser.add_argument("--team-lead-model", default=os.environ.get("TEAM_LEAD_MODEL"), help="Model for tool-less Team Lead. Defaults to --model")
    parser.add_argument("--team-lead-timeout", type=float, default=120.0, help="Team Lead direct LLM timeout. Default: 120")
    parser.add_argument("--team-lead-max-attempts", type=int, default=3, help="Team Lead JSON decision attempts. Default: 3")
    parser.add_argument("--prompt", required=True, help="Task prompt")
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
    return parser


async def _amain(args: argparse.Namespace) -> dict[str, Any]:
    instance = OpenHandsInstance(args.endpoint, api_key=args.api_key, default_model=args.model)
    runner = OpenHandsRoleRunner(instance, summary_max_attempts=args.summary_max_attempts)
    graph = build_development_graph() if args.workflow == "development" else build_team_lead_graph() if args.workflow == "team-lead" else build_single_role_graph()
    state = {
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

    if args.output_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human_result(result, color=not args.no_color)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
