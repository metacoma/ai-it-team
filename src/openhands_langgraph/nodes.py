from __future__ import annotations

from typing import Any, Optional
import json
import time
from datetime import datetime, timezone

try:
    from langchain_core.runnables import RunnableConfig
except ImportError:  # LangGraph is an optional extra.
    RunnableConfig = dict[str, Any]  # type: ignore[misc,assignment]

from openhands import AppConversationStart, OpenHandsInstance, OpenHandsRoleRunner

from .prompts import (
    BLOCK_ACTIONS,
    TEAM_LEAD_ALLOWED_ROLES,
    TEAM_LEAD_RUN_ACTIONS,
    TEAM_LEAD_STOP_ACTIONS,
    NEED_FIX_ACTIONS,
    PASS_ACTIONS,
    build_role_prompt,
    build_team_lead_decision_prompt,
    build_role_summary_instructions,
    normalize_action,
    role_input_summary,
)
from .state import JsonDict, OpenHandsGraphState
from .team_lead import DirectLLMTeamLeadRunner, TeamLeadDecision, TeamLeadDecisionResult
from .reports import compact_report_summary, parse_role_report, report_required_target_gaps


class OpenHandsLangGraphError(RuntimeError):
    """Configuration/runtime error raised by the LangGraph integration layer."""


def _resolve_role_model(role: str, state: OpenHandsGraphState) -> str | None:
    """Resolve the model for a role, with YAML config override.

    Precedence:
    1. YAML config: state["role_models"][role]
    2. Global model: state["model"]
    3. None (falls back to instance.default_model)
    """
    role_models = state.get("role_models")
    if isinstance(role_models, dict):
        model = role_models.get(role)
        if model and isinstance(model, str) and model.strip():
            return model.strip()
    return state.get("model")


_COLOR = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "scout": "\033[36m",
    "research": "\033[34m",
    "senior_staff_engineer": "\033[95m",
    "architect": "\033[35m",
    "coder": "\033[32m",
    "qa": "\033[92m",
    "reviewer": "\033[33m",
    "team_lead": "\033[96m",
    "publisher": "\033[94m",
    "error": "\033[31m",
    "ok": "\033[32m",
}


def _graph_trace_enabled(config: Optional[RunnableConfig]) -> bool:
    cfg = _configurable(config)
    return bool(cfg.get("openhands_graph_trace", False))


def _graph_trace_color(config: Optional[RunnableConfig]) -> bool:
    cfg = _configurable(config)
    return bool(cfg.get("openhands_graph_color", True))


def _c(text: str, color: str, config: Optional[RunnableConfig]) -> str:
    if not _graph_trace_color(config):
        return text
    return f"{_COLOR.get(color, '')}{text}{_COLOR['reset']}"


def _short(value: Any, limit: int = 240) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _trace_role_input(role: str, state: OpenHandsGraphState, config: Optional[RunnableConfig]) -> None:
    if not _graph_trace_enabled(config):
        return
    role_key = (role or "role").lower()
    title = f"▶ {role_key.upper()} input"
    print(_c(title, role_key, config))
    for line in role_input_summary(role_key, state):
        print(f"  {_c('•', 'dim', config)} {line}")


def _trace_role_result(role: str, result_dict: JsonDict, config: Optional[RunnableConfig]) -> None:
    if not _graph_trace_enabled(config):
        return
    role_key = (role or "role").lower()
    summary = result_dict.get("summary") or {}
    action = result_dict.get("summary_action") or summary.get("action") or ""
    status = result_dict.get("summary_status") or summary.get("status") or result_dict.get("status") or ""
    risk = result_dict.get("risk_level") or summary.get("risk_level") or ""
    blocking = result_dict.get("blocking") if result_dict.get("blocking") is not None else summary.get("blocking")
    summary_text = summary.get("summary") if isinstance(summary, dict) else ""
    print(_c(f"✓ {role_key.upper()} result", "ok" if result_dict.get("ok") else "error", config))
    print(f"  {_c('•', 'dim', config)} status: {status or 'unknown'}")
    print(f"  {_c('•', 'dim', config)} action: {action or 'unknown'}")
    print(f"  {_c('•', 'dim', config)} risk: {risk or 'unknown'}")
    print(f"  {_c('•', 'dim', config)} blocking: {blocking}")
    if summary_text:
        print(f"  {_c('•', 'dim', config)} summary: {_short(summary_text)}")
    if result_dict.get("conversation_id"):
        print(f"  {_c('•', 'dim', config)} conversation: {result_dict.get('conversation_id')}")


def _configurable(config: Optional[RunnableConfig]) -> JsonDict:
    if config is None:
        return {}
    if isinstance(config, dict):
        value = config.get("configurable", {})
        return value if isinstance(value, dict) else {}
    value = getattr(config, "configurable", {})
    return value if isinstance(value, dict) else {}


def _workflow_ui(config: Optional[RunnableConfig]) -> Any:
    return _configurable(config).get("openhands_workflow_ui")


def _append_error(state: OpenHandsGraphState, error: str) -> OpenHandsGraphState:
    errors = list(state.get("errors") or [])
    errors.append(error)
    return {
        "errors": errors,
        "final_status": "failed",
        "last_role_result": None,
    }


def _drop_recovered_role_errors(errors: list[str], role: str) -> list[str]:
    """Remove active runtime errors for a role after that role later succeeds.

    Failed attempts remain visible in ``role_results`` as historical evidence, but
    they must not stay in the active ``errors`` list after a later successful
    retry. Otherwise a recovered QA/reviewer failure can still appear as a final
    blocker and confuse Team Lead routing or human-readable output.
    """
    prefix = f"{str(role or '').strip().lower()}:"
    if not prefix or prefix == ":":
        return errors
    recovered: list[str] = []
    for error in errors:
        if str(error).strip().lower().startswith(prefix):
            continue
        recovered.append(error)
    return recovered


def _build_runner(state: OpenHandsGraphState, config: Optional[RunnableConfig]) -> OpenHandsRoleRunner:
    cfg = _configurable(config)
    runner = cfg.get("openhands_runner")
    if isinstance(runner, OpenHandsRoleRunner):
        return runner

    instance = cfg.get("openhands_instance")
    if not isinstance(instance, OpenHandsInstance):
        endpoint = cfg.get("openhands_endpoint") or state.get("endpoint")
        if not endpoint:
            raise OpenHandsLangGraphError(
                "LangGraph config must provide configurable.openhands_runner, "
                "configurable.openhands_instance, or configurable.openhands_endpoint"
            )
        instance = OpenHandsInstance(
            endpoint=str(endpoint),
            api_key=cfg.get("openhands_api_key"),
            default_model=cfg.get("openhands_default_model"),
        )

    return OpenHandsRoleRunner(
        instance,
        summary_instructions=cfg.get("summary_instructions") or OpenHandsRoleRunner(instance).summary_instructions,
        summary_max_attempts=int(cfg.get("summary_max_attempts", 0)),
    )


def _result_for_state(result: Any, *, include_answer: bool) -> JsonDict:
    if hasattr(result, "to_dict"):
        return result.to_dict(
            include_answer=include_answer,
            include_raw_summary=False,
            include_attempt_text=False,
        )
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    raise TypeError(f"Unsupported role result type: {type(result)!r}")


def _include_answer(config: Optional[RunnableConfig]) -> bool:
    return bool(_configurable(config).get("include_answer_in_state", True))


def _base_run_options(state: OpenHandsGraphState, config: Optional[RunnableConfig]) -> JsonDict:
    cfg = _configurable(config)
    run_options: JsonDict = {}
    run_options.update(cfg.get("openhands_run_options") or {})
    run_options.update(state.get("role_run_options") or {})
    return run_options


def _role_state_key(role: str) -> str:
    role = (role or "role").lower()
    if role in {"team_lead", "scout", "research", "senior_staff_engineer", "architect", "coder", "qa", "reviewer", "publisher"}:
        return f"{role}_result"
    return "last_role_result"


def _role_conversation_title(role: str, state: OpenHandsGraphState) -> str:
    task = str(state.get("user_task") or state.get("prompt") or "OpenHands task").replace("\n", " ").strip()
    task = " ".join(task.split())
    if len(task) > 96:
        task = task[:93].rstrip() + "..."
    role_name = (role or "role").strip() or "role"
    return f"{role_name}: {task}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _round_seconds(value: float) -> float:
    return round(max(0.0, value), 3)


def _session_key(role: str, role_instance: str | None) -> str:
    role = (role or "role").lower()
    return role_instance or f"{role}-1"


def _role_sessions(state: OpenHandsGraphState) -> JsonDict:
    sessions = state.get("role_sessions") or {}
    return dict(sessions) if isinstance(sessions, dict) else {}


def _session_start_from_state(session: JsonDict) -> AppConversationStart | None:
    conversation_id = session.get("conversation_id")
    if not conversation_id:
        return None
    return AppConversationStart(
        conversation_id=str(conversation_id),
        sandbox_id=session.get("sandbox_id"),
        agent_server_url=session.get("agent_server_url"),
        conversation_url=session.get("conversation_url"),
        session_api_key=session.get("session_api_key"),
    )


def _session_known_event_ids(session: JsonDict) -> set[str]:
    raw = session.get("known_event_ids") or []
    if isinstance(raw, (list, tuple, set, frozenset)):
        return {str(item) for item in raw if item}
    return set()


def _update_role_session_from_result(
    state: OpenHandsGraphState,
    *,
    role: str,
    role_instance: str | None,
    result: Any,
) -> JsonDict:
    sessions = _role_sessions(state)
    key = _session_key(role, role_instance)
    conversation = getattr(result, "conversation", None)
    start = getattr(conversation, "start", None) if conversation is not None else None
    conversation_id = getattr(result, "conversation_id", None) or getattr(start, "conversation_id", None)
    sessions[key] = {
        "role": role,
        "role_instance": role_instance,
        "conversation_id": conversation_id,
        "sandbox_id": getattr(start, "sandbox_id", None),
        "agent_server_url": getattr(start, "agent_server_url", None),
        "conversation_url": getattr(start, "conversation_url", None),
        # Do not store session_api_key in graph state/output. attach_conversation()
        # refreshes runtime metadata before follow-up messages when needed.
        "known_event_ids": sorted(getattr(result, "seen_event_ids", frozenset()) or []),
        "known_event_count": len(getattr(result, "seen_event_ids", frozenset()) or []),
    }
    return sessions


def _classify_role_failure(error: BaseException | str) -> tuple[str, bool]:
    """Classify runtime failures for Team Lead retry policy.

    This is deliberately heuristic: OpenHands/LiteLLM error strings vary across
    versions, but the orchestration layer only needs a stable category and a
    conservative retryability signal.
    """
    text = str(error or "")
    lowered = text.lower()
    if "failed to parse tool call arguments as json" in lowered or "parse_error" in lowered:
        return "llm_tool_call_json_parse_error", True
    if "without an assistant answer" in lowered or "cannot summarize" in lowered:
        return "missing_assistant_answer", True
    if "websocket" in lowered or "connection" in lowered or "timeout" in lowered:
        return "openhands_transport_error", True
    if "summary did not become valid json" in lowered:
        return "summary_json_parse_error", True
    return "role_runtime_error", True


def _synthetic_failed_role_result(
    state: OpenHandsGraphState,
    *,
    role: str,
    role_instance: str | None,
    error: BaseException | str,
    started_at: str,
    duration_seconds: float,
    persistent_session: bool = False,
) -> JsonDict:
    error_text = str(error or "Unknown role failure")
    error_type, retryable = _classify_role_failure(error_text)
    session = _role_sessions(state).get(_session_key(role, role_instance)) if persistent_session else None
    conversation_id = session.get("conversation_id") if isinstance(session, dict) else None
    finished_at = _utc_now_iso()
    summary = {
        "valid": True,
        "status": "failed",
        "summary": (
            f"{role} runtime failure before producing a usable assistant answer/report "
            f"({error_type}). No downstream role may assume this role completed."
        ),
        "action": "FAILED",
        "risk_level": "high",
        "blocking": True,
        "blocking_summary": [error_text],
    }
    result: JsonDict = {
        "role": role,
        "role_instance": role_instance,
        "conversation_id": conversation_id or "",
        "status": "failed",
        "ok": False,
        "summary_status": "failed",
        "summary_action": "FAILED",
        "risk_level": "high",
        "blocking": True,
        "summary": summary,
        "summary_attempt_count": 0,
        "summary_attempts": [],
        "error": error_text,
        "error_type": error_type,
        "retryable": retryable,
        "answer": "",
        "answer_run": {
            "text": "",
            "status": "failed",
            "conversation_id": conversation_id or "",
            "start": {"conversation_id": conversation_id or "", "status": "failed"},
            "has_answer": False,
            "seen_event_count": 0,
        },
        "seen_event_count": 0,
        "metrics": {
            "role": role,
            "role_instance": role_instance,
            "status": "failed",
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "summary_attempt_count": 0,
            "answer_chars": 0,
            "summary_chars": len(summary["summary"]),
            "error": error_text,
            "error_type": error_type,
            "retryable": retryable,
        },
    }
    return result


def _is_usable_role_result(result: JsonDict | None) -> bool:
    if not isinstance(result, dict) or not result:
        return False
    if result.get("ok") is not True:
        return False
    summary = result.get("summary") or {}
    if isinstance(summary, dict) and normalize_action(summary.get("action")) in BLOCK_ACTIONS:
        return False
    return bool((result.get("answer") or "").strip() or result.get("summary"))


def _latest_result_for_role(state: OpenHandsGraphState, role: str) -> JsonDict | None:
    """Return the latest result for a role from append-only workflow history.

    Role-specific state keys such as ``qa_result`` are convenient snapshots, but
    retry cycles can leave stale snapshots in tests, custom reducers, or resumed
    runs. The append-only ``role_results`` list is the source of truth for
    ordering, so scan it first and only fall back to the snapshot key.
    """
    for result in reversed(list(state.get("role_results") or [])):
        if isinstance(result, dict) and str(result.get("role") or "").lower() == role:
            return result
    direct = state.get(f"{role}_result")
    if isinstance(direct, dict) and direct:
        return direct
    return None


def _latest_result_index_for_role(state: OpenHandsGraphState, role: str) -> tuple[int | None, JsonDict | None]:
    results = list(state.get("role_results") or [])
    for idx in range(len(results) - 1, -1, -1):
        result = results[idx]
        if isinstance(result, dict) and str(result.get("role") or "").lower() == role:
            return idx, result
    direct = state.get(f"{role}_result")
    if isinstance(direct, dict) and direct:
        return None, direct
    return None, None


def _latest_result_for_role_after_index(
    state: OpenHandsGraphState,
    role: str,
    after_index: int | None,
) -> JsonDict | None:
    results = list(state.get("role_results") or [])
    for idx in range(len(results) - 1, -1, -1):
        if after_index is not None and idx <= after_index:
            break
        result = results[idx]
        if isinstance(result, dict) and str(result.get("role") or "").lower() == role:
            return result
    if after_index is None:
        direct = state.get(f"{role}_result")
        if isinstance(direct, dict) and direct:
            return direct
    return None


def _latest_coder_pass_index(state: OpenHandsGraphState) -> int | None:
    results = list(state.get("role_results") or [])
    for idx in range(len(results) - 1, -1, -1):
        result = results[idx]
        if not isinstance(result, dict) or str(result.get("role") or "").lower() != "coder":
            continue
        summary = result.get("summary") or {}
        action = normalize_action(result.get("summary_action") or (summary.get("action") if isinstance(summary, dict) else None))
        if _is_usable_role_result(result) and action in PASS_ACTIONS:
            return idx
        return idx
    return None


async def _run_role_with_prompt(
    state: OpenHandsGraphState,
    config: Optional[RunnableConfig],
    *,
    role: str,
    role_instance: str | None = None,
    prompt: str,
    summary_instructions: str | None = None,
    persistent_session: bool = False,
) -> OpenHandsGraphState:
    _trace_role_input(role, state, config)
    ui = _workflow_ui(config)
    if ui is not None:
        try:
            ui.role_start(role, prompt, title=_role_conversation_title(role, state), state=state)
        except Exception:
            pass
    event_callback = None
    if ui is not None:
        try:
            event_callback = ui.role_event_callback(role)
        except Exception:
            event_callback = None
    started_at = _utc_now_iso()
    started_monotonic = time.monotonic()
    try:
        runner = _build_runner(state, config)
        run_options = _base_run_options(state, config)
        conversation_params: JsonDict = dict(state.get("conversation_params") or {})
        session_key = _session_key(role, role_instance)
        session = _role_sessions(state).get(session_key) if persistent_session else None
        conversation_start = _session_start_from_state(session) if isinstance(session, dict) else None
        known_event_ids = _session_known_event_ids(session) if isinstance(session, dict) else None

        result = await runner.run_role(
            role=role,
            role_instance=role_instance,
            prompt=prompt,
            conversation_start=conversation_start,
            known_event_ids=known_event_ids,
            model=_resolve_role_model(role, state),
            repository=state.get("repository"),
            branch=state.get("branch"),
            git_provider=state.get("git_provider"),
            sandbox_id=state.get("sandbox_id"),
            title=_role_conversation_title(role, state),
            extra_payload=state.get("extra_payload"),
            summary_instructions=summary_instructions,
            event_callback=event_callback,
            **conversation_params,
            **run_options,
        )
    except Exception as exc:
        duration_seconds = _round_seconds(time.monotonic() - started_monotonic)
        if isinstance(exc, OpenHandsLangGraphError):
            patch = _append_error(state, str(exc))
            patch["last_role_metrics"] = {
                "role": role,
                "role_instance": role_instance,
                "status": "failed",
                "started_at": started_at,
                "finished_at": _utc_now_iso(),
                "duration_seconds": duration_seconds,
                "error": str(exc),
            }
            return patch
        failed_result = _synthetic_failed_role_result(
            state,
            role=role,
            role_instance=role_instance,
            error=exc,
            started_at=started_at,
            duration_seconds=duration_seconds,
            persistent_session=persistent_session,
        )
        _trace_role_result(role, failed_result, config)
        ui = _workflow_ui(config)
        if ui is not None:
            try:
                ui.role_result(role, failed_result)
            except Exception:
                pass
        role_results = list(state.get("role_results") or [])
        role_results.append(failed_result)
        errors = list(state.get("errors") or [])
        errors.append(f"{role}: {exc}")
        patch: OpenHandsGraphState = {
            "role_results": role_results,
            "last_role_result": failed_result,
            "last_role_metrics": failed_result["metrics"],
            "final_answer": failed_result["summary"]["summary"],
            "final_status": "failed",
            "errors": errors,
        }
        patch[_role_state_key(role)] = failed_result  # type: ignore[literal-required]
        if persistent_session:
            patch["role_sessions"] = _role_sessions(state)
        return patch

    result_dict = _result_for_state(result, include_answer=_include_answer(config))
    duration_seconds = _round_seconds(time.monotonic() - started_monotonic)
    result_dict["metrics"] = {
        "role": role,
        "role_instance": role_instance,
        "started_at": started_at,
        "finished_at": _utc_now_iso(),
        "duration_seconds": duration_seconds,
        "summary_attempt_count": result_dict.get("summary_attempt_count", len(result.summary_attempts)),
        "answer_chars": len(result.answer or ""),
        "summary_chars": len(result.summary_text or ""),
    }
    result_dict = _postprocess_role_result(role, result_dict)
    _trace_role_result(role, result_dict, config)
    if ui is not None:
        try:
            ui.role_result(role, result_dict)
        except Exception:
            pass
    role_results = list(state.get("role_results") or [])
    role_results.append(result_dict)
    errors = list(state.get("errors") or [])
    if result_dict.get("ok") is True:
        errors = _drop_recovered_role_errors(errors, role)
    updated_sessions = _update_role_session_from_result(
        state,
        role=role,
        role_instance=role_instance,
        result=result,
    ) if persistent_session else state.get("role_sessions")

    patch: OpenHandsGraphState = {
        "role_results": role_results,
        "last_role_result": result_dict,
        "last_role_metrics": result_dict["metrics"],
        "final_answer": result.answer,
        "final_status": "completed" if result.ok else "failed",
        "errors": errors,
    }
    validation_profile = _role_report_validation_profile(result_dict)
    if validation_profile:
        patch["validation_profile"] = validation_profile
    if updated_sessions is not None:
        patch["role_sessions"] = updated_sessions
    patch[_role_state_key(role)] = result_dict  # type: ignore[literal-required]
    return patch


async def run_openhands_role_node(state: OpenHandsGraphState, config: Optional[RunnableConfig] = None) -> OpenHandsGraphState:
    """Run one OpenHands role and append its serializable result to graph state.

    This is the Stage 1 MVP node. It intentionally performs no routing and no
    multi-role orchestration; later graphs can compose this primitive.
    """
    prompt = state.get("prompt") or state.get("user_task")
    if not prompt:
        return _append_error(state, "state must contain prompt or user_task")
    return await _run_role_with_prompt(
        state,
        config,
        role=state.get("role") or "role",
        role_instance=state.get("role_instance"),
        prompt=prompt,
    )


async def scout_node(state: OpenHandsGraphState, config: Optional[RunnableConfig] = None) -> OpenHandsGraphState:
    return await _run_role_with_prompt(
        state,
        config,
        role="scout",
        role_instance="scout-1",
        prompt=build_role_prompt("scout", state),
        summary_instructions=build_role_summary_instructions("scout"),
    )


async def research_node(state: OpenHandsGraphState, config: Optional[RunnableConfig] = None) -> OpenHandsGraphState:
    return await _run_role_with_prompt(
        state,
        config,
        role="research",
        role_instance="research-1",
        prompt=build_role_prompt("research", state),
        summary_instructions=build_role_summary_instructions("research"),
    )


async def senior_staff_engineer_node(state: OpenHandsGraphState, config: Optional[RunnableConfig] = None) -> OpenHandsGraphState:
    return await _run_role_with_prompt(
        state,
        config,
        role="senior_staff_engineer",
        role_instance="senior_staff_engineer-1",
        prompt=build_role_prompt("senior_staff_engineer", state),
        summary_instructions=build_role_summary_instructions("senior_staff_engineer"),
    )


def senior_staff_decision_node(state: OpenHandsGraphState) -> OpenHandsGraphState:
    """Gate architecture planning on a Senior Staff execution contract.

    Senior Staff may request more research/scout/human input, but LangGraph owns
    the routing. The role cannot arbitrarily launch roles.
    """
    if state.get("errors"):
        return {"next_node": "end", "final_status": "failed"}

    staff_result = state.get("senior_staff_engineer_result") or state.get("last_role_result") or {}
    summary = staff_result.get("summary") or {}
    action = normalize_action(staff_result.get("summary_action") or summary.get("action"))

    if action in PASS_ACTIONS or action in {"PROCEED", "PROCEED_TO_ARCHITECT", "STRATEGY_READY"}:
        return {
            "next_node": "architect",
            "final_status": "strategy_ready",
            "final_answer": "Senior Staff returned an execution contract and strategy; routing to Architect.",
        }

    if action in NEED_FIX_ACTIONS or action in {"NEED_MORE_RESEARCH", "NEED_MORE_SCOUT", "REWORK_STRATEGY", "ASK_HUMAN"}:
        return {
            "next_node": "end",
            "final_status": "needs_human_review",
            "final_answer": f"Senior Staff requested additional input before architecture: {action}",
        }

    if action in BLOCK_ACTIONS or staff_result.get("blocking") is True:
        return {
            "next_node": "end",
            "final_status": "blocked",
            "final_answer": "Development workflow blocked by Senior Staff execution contract gate.",
        }

    return {
        "next_node": "end",
        "final_status": "needs_human_review",
        "final_answer": f"Senior Staff action was ambiguous: {action}",
    }


async def architect_node(state: OpenHandsGraphState, config: Optional[RunnableConfig] = None) -> OpenHandsGraphState:
    return await _run_role_with_prompt(
        state,
        config,
        role="architect",
        role_instance="architect-1",
        prompt=build_role_prompt("architect", state),
        summary_instructions=build_role_summary_instructions("architect"),
    )


async def coder_node(state: OpenHandsGraphState, config: Optional[RunnableConfig] = None) -> OpenHandsGraphState:
    current_iteration = int(state.get("current_iteration") or 0)
    patch = await _run_role_with_prompt(
        state,
        config,
        role="coder",
        role_instance=f"coder-{current_iteration + 1}",
        prompt=build_role_prompt("coder", state),
        summary_instructions=build_role_summary_instructions("coder"),
    )
    patch["current_iteration"] = current_iteration
    return patch


async def qa_node(state: OpenHandsGraphState, config: Optional[RunnableConfig] = None) -> OpenHandsGraphState:
    return await _run_role_with_prompt(
        state,
        config,
        role="qa",
        role_instance=f"qa-{int(state.get('current_iteration') or 0) + 1}",
        prompt=build_role_prompt("qa", state),
        summary_instructions=build_role_summary_instructions("qa"),
    )




def qa_decision_node(state: OpenHandsGraphState) -> OpenHandsGraphState:
    """Route after QA validation.

    QA owns build/test/smoke evidence. Reviewer must not run until QA returned
    PASS; if QA finds fixable validation failures, route back to coder.
    """
    if state.get("errors"):
        return {"next_node": "end", "final_status": "failed"}

    qa_result = state.get("qa_result") or state.get("last_role_result") or {}
    action = normalize_action(qa_result.get("summary_action") or (qa_result.get("summary") or {}).get("action"))
    current_iteration = int(state.get("current_iteration") or 0)
    max_fix_iterations = int(state.get("max_fix_iterations") if state.get("max_fix_iterations") is not None else 2)

    if action in PASS_ACTIONS:
        ok, reason = _qa_validation_evidence_ok(qa_result)
        if not ok:
            return {
                "next_node": "end",
                "final_status": "needs_human_review",
                "final_answer": f"QA returned PASS without required build/test evidence: {reason}",
            }
        return {
            "next_node": "reviewer",
            "final_status": "qa_passed",
            "final_answer": "QA returned PASS with build/test evidence; routing to Reviewer.",
        }

    if action in NEED_FIX_ACTIONS:
        if current_iteration < max_fix_iterations:
            return {
                "next_node": "coder",
                "current_iteration": current_iteration + 1,
                "final_status": "needs_fix",
                "final_answer": "QA requested fixes; routing back to Coder.",
            }
        return {
            "next_node": "end",
            "final_status": "needs_human_review",
            "final_answer": "QA still requested fixes after max_fix_iterations.",
        }

    if action in BLOCK_ACTIONS or qa_result.get("blocking") is True:
        return {
            "next_node": "end",
            "final_status": "blocked",
            "final_answer": "Development workflow blocked by QA validation.",
        }

    return {
        "next_node": "end",
        "final_status": "needs_human_review",
        "final_answer": f"QA action was ambiguous: {action}",
    }


async def reviewer_node(state: OpenHandsGraphState, config: Optional[RunnableConfig] = None) -> OpenHandsGraphState:
    return await _run_role_with_prompt(
        state,
        config,
        role="reviewer",
        role_instance=f"reviewer-{int(state.get('current_iteration') or 0) + 1}",
        prompt=build_role_prompt("reviewer", state),
        summary_instructions=build_role_summary_instructions("reviewer"),
    )


async def publisher_node(state: OpenHandsGraphState, config: Optional[RunnableConfig] = None) -> OpenHandsGraphState:
    patch = await _run_role_with_prompt(
        state,
        config,
        role="publisher",
        role_instance="publisher-1",
        prompt=build_role_prompt("publisher", state),
        summary_instructions=build_role_summary_instructions("publisher"),
    )
    publisher_result = patch.get("publisher_result") or patch.get("last_role_result") or {}
    summary = publisher_result.get("summary") or {}
    action = normalize_action(publisher_result.get("summary_action") or summary.get("action"))
    if action in PASS_ACTIONS:
        patch["final_status"] = "completed"
        patch["final_answer"] = "Development workflow completed: Publisher pushed changes and created or found a pull request."
    elif action in NEED_FIX_ACTIONS:
        patch["final_status"] = "needs_human_review"
        patch["final_answer"] = "Publisher requested fixes after reviewer PASS; human review is required before retrying."
    elif action in BLOCK_ACTIONS or publisher_result.get("blocking") is True:
        patch["final_status"] = "publish_blocked"
        patch["final_answer"] = "Development workflow blocked by Publisher during push/PR creation."
    return patch


def _team_lead_decision_from_result(result_dict: JsonDict) -> JsonDict:
    summary = result_dict.get("summary") or {}
    if not isinstance(summary, dict):
        summary = {}
    decision = dict(summary)
    decision["action"] = normalize_action(result_dict.get("summary_action") or summary.get("action"))
    next_role = decision.get("next_role") or decision.get("role")
    if next_role is not None:
        decision["next_role"] = str(next_role).strip().lower()
    return decision


def _has_reviewer_pass(state: OpenHandsGraphState) -> bool:
    reviewer = _latest_reviewer_result_for_current_qa_validation(state) or {}
    ok, _ = _reviewer_validation_review_ok(reviewer)
    return ok


def _qa_pass_gate(state: OpenHandsGraphState) -> tuple[bool, str | None]:
    qa = _latest_qa_result_for_current_coder_attempt(state) or {}
    return _qa_validation_evidence_ok(qa)


def _reviewer_pass_gate(state: OpenHandsGraphState) -> tuple[bool, str | None]:
    reviewer = _latest_reviewer_result_for_current_qa_validation(state) or {}
    return _reviewer_validation_review_ok(reviewer)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1", "pass", "passed", "ok"}
    return bool(value)


def _nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and any(str(item).strip() for item in value)


def _strip_negative_validation_phrases(text: str) -> str:
    """Avoid false positives from phrases like 'not syntax-only validation'."""
    cleaned = text
    for phrase in [
        "not syntax-only validation",
        "not syntax only validation",
        "not syntax-level validation",
        "not syntax level validation",
        "not syntax-only",
        "not syntax only",
        "not syntax-level",
        "not syntax level",
    ]:
        cleaned = cleaned.replace(phrase, "runtime validation")
    return cleaned


def _iter_json_objects_from_text(text: str) -> list[JsonDict]:
    """Return JSON objects embedded in arbitrary LLM prose/Markdown.

    Role answers often include a final "Validation Evidence JSON" block while
    the compact summary may omit that extra object. Guards must inspect the full
    answer too, otherwise valid QA evidence is lost during summarizing.
    """
    if not text:
        return []
    objects: list[JsonDict] = []
    starts = [idx for idx, ch in enumerate(text) if ch == "{"]
    for start in starts:
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(text[start : idx + 1])
                    except Exception:
                        break
                    if isinstance(data, dict):
                        objects.append(data)
                    break
    return objects


def _find_mapping_key(data: Any, key: str) -> JsonDict | None:
    if isinstance(data, dict):
        value = data.get(key)
        if isinstance(value, dict):
            return value
        for child in data.values():
            found = _find_mapping_key(child, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for child in data:
            found = _find_mapping_key(child, key)
            if found is not None:
                return found
    return None


def _extract_answer_object(result: JsonDict, key: str) -> JsonDict | None:
    for source_key in ("answer", "raw_summary"):
        text = str(result.get(source_key) or "")
        for obj in _iter_json_objects_from_text(text):
            found = _find_mapping_key(obj, key)
            if found is not None:
                return found
    return None


def _reviewer_text(result: JsonDict) -> str:
    summary = result.get("summary") or {}
    parts: list[str] = []
    if isinstance(summary, dict):
        for key in ("summary", "validation_review", "review_validation"):
            value = summary.get(key)
            if value:
                parts.append(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value))
    for key in ("answer", "raw_summary"):
        value = result.get(key)
        if value:
            parts.append(str(value))
    return "\n".join(parts)


def _contains_any(text: str, markers: list[str]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def _synthesize_reviewer_validation_review_from_text(result: JsonDict) -> JsonDict | None:
    """Recover reviewer validation evidence from explicit prose when JSON was lost.

    Local models sometimes produce a good review report but omit the required
    ``validation_review`` JSON or the summary step drops it. This fallback is
    intentionally conservative: it only accepts prose that clearly says the
    reviewer considered QA build evidence, QA runtime/test evidence, and a
    non-syntax validation level. Vague text such as "looks good" still fails.
    """
    text = _reviewer_text(result)
    lowered = text.lower()
    if not lowered.strip():
        return None

    qa_build_ok = (
        _contains_any(lowered, ["qa", "validation", "runtime validation", "full runtime validation"])
        and _contains_any(lowered, ["build", "compile", "compiled", "gradle", "java build"])
        and _contains_any(lowered, ["pass", "passed", "success", "successful", "cleanly", "ok"])
    )
    qa_test_ok = (
        _contains_any(lowered, ["qa", "validation", "runtime validation", "smoke", "integration", "test"])
        and _contains_any(lowered, ["test", "tests", "smoke", "integration", "runtime"])
        and _contains_any(lowered, ["pass", "passed", "all tests", "success", "successful", "validated", "verified"])
    )
    qa_level_ok = _contains_any(
        lowered,
        [
            "ci-like",
            "ci like",
            "targeted_runtime",
            "targeted runtime",
            "targeted_integration",
            "targeted integration",
            "runtime validation",
            "integration",
            "smoke",
            "xvfb",
            "freeplane runtime",
        ],
    )
    syntax_only_rejected = (
        _contains_any(lowered, ["runtime validation", "integration", "smoke", "xvfb", "freeplane runtime", "ci-like", "ci like"])
        or _contains_any(lowered, ["not syntax-only", "not syntax only", "syntax-only validation rejected", "syntax only rejected"])
    )

    if not (qa_build_ok and qa_test_ok and qa_level_ok and syntax_only_rejected):
        return None

    lint_commands: list[str] = []
    for line in text.splitlines():
        low = line.lower()
        if any(marker in low for marker in ["lint", "static", "syntax", "compile", "javac", "ruby -c", "python -m py_compile"]):
            stripped = line.strip(" -`	")
            if stripped:
                lint_commands.append(stripped[:240])
        if len(lint_commands) >= 8:
            break

    return {
        "qa_build_evidence_ok": True,
        "qa_test_evidence_ok": True,
        "qa_validation_level_ok": True,
        "environment_reconstruction_reviewed": _contains_any(lowered, ["xvfb", "freeplane", "environment", "runtime", "sandbox", "layout"]),
        "syntax_only_rejected": True,
        "lint_commands": lint_commands,
        "setup_commands_reviewed": [],
        "validation_gaps": [],
        "source": "reviewer_prose_fallback",
    }


def _ensure_summary_mapping(result: JsonDict) -> JsonDict:
    summary = result.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        result["summary"] = summary
    return summary


def _role_report_validation_profile(result: JsonDict) -> JsonDict | None:
    report = result.get("role_report") if isinstance(result, dict) else None
    if isinstance(report, dict) and isinstance(report.get("validation_profile"), dict) and report.get("validation_profile"):
        return report["validation_profile"]
    summary = result.get("summary") if isinstance(result, dict) else None
    if isinstance(summary, dict) and isinstance(summary.get("validation_profile"), dict) and summary.get("validation_profile"):
        return summary["validation_profile"]
    return None


SCOUT_FORBIDDEN_FACTS_ONLY_MARKERS = [
    "root cause hypothesis",
    "root-cause hypothesis",
    "candidate root cause",
    "candidate cause",
    "likely root cause",
    "most likely cause",
    "the root cause is",
    "root cause identified",
    "primary:",
    "hypothesis:",
    "hypotheses",
]


def _scout_forbidden_markers(text: str) -> list[str]:
    lowered = str(text or "").lower()
    return [marker for marker in SCOUT_FORBIDDEN_FACTS_ONLY_MARKERS if marker in lowered]


def _postprocess_role_result(role: str, result: JsonDict) -> JsonDict:
    """Normalize role evidence before LangGraph routing decisions use it.

    v46 introduces typed role reports as the primary context for Team Lead.
    Existing summary/answer evidence is still promoted for backwards
    compatibility, but semantic delivery decisions now belong to Team Lead.
    """
    role = (role or "").lower()
    summary = _ensure_summary_mapping(result)
    role_instance = str(result.get("role_instance") or f"{role}-1")
    report_id = result.get("report_id") or f"{role_instance}:{result.get('conversation_id') or result.get('summary_attempt_count') or 'result'}"
    result["report_id"] = str(report_id)

    role_report, report_source = parse_role_report(
        role,
        answer=str(result.get("answer") or ""),
        summary=summary,
        role_instance=role_instance,
        fallback_report_id=str(report_id),
    )
    if role_report is not None:
        result["role_report"] = role_report
        result["role_report_source"] = report_source
        summary.setdefault("role_report", role_report)
        if isinstance(role_report.get("validation_profile"), dict) and role_report.get("validation_profile"):
            summary.setdefault("validation_profile", role_report["validation_profile"])

    if role == "qa" and isinstance((result.get("role_report") or {}).get("validation"), dict) and not isinstance(summary.get("validation"), dict):
        summary["validation"] = result["role_report"]["validation"]
        result["qa_validation_evidence_source"] = "role_report"

    if role == "reviewer" and isinstance((result.get("role_report") or {}).get("validation_review"), dict) and not isinstance(summary.get("validation_review"), dict):
        summary["validation_review"] = result["role_report"]["validation_review"]
        result["reviewer_validation_review_source"] = "role_report"

    if role == "publisher" and isinstance((result.get("role_report") or {}).get("pr_checks"), dict) and not isinstance(summary.get("pr_checks"), dict):
        summary["pr_checks"] = result["role_report"]["pr_checks"]
        result["publisher_pr_checks_source"] = "role_report"

    if role == "qa" and not isinstance(summary.get("validation"), dict):
        validation = _extract_answer_object(result, "validation")
        if validation is not None:
            summary["validation"] = validation
            result["qa_validation_evidence_source"] = "answer"

    if role == "qa" and isinstance(summary.get("validation"), dict):
        profile = _role_report_validation_profile(result)
        if isinstance(profile, dict) and profile:
            gaps = report_required_target_gaps(profile, summary["validation"])
            if gaps:
                summary["validation"].setdefault("profile_gaps", gaps)
                result["qa_validation_profile_gaps"] = gaps

    if role == "reviewer" and not isinstance(summary.get("validation_review"), dict):
        review = _extract_answer_object(result, "validation_review")
        if review is not None:
            summary["validation_review"] = review
            result["reviewer_validation_review_source"] = "answer"
        else:
            prose_review = _synthesize_reviewer_validation_review_from_text(result)
            if prose_review is not None:
                summary["validation_review"] = prose_review
                result["reviewer_validation_review_source"] = "prose_fallback"

    if role == "publisher" and not isinstance(summary.get("pr_checks"), dict):
        pr_checks = _extract_answer_object(result, "pr_checks")
        if pr_checks is not None:
            summary["pr_checks"] = pr_checks
            result["publisher_pr_checks_source"] = "answer"

    if role == "publisher":
        action = normalize_action(result.get("summary_action") or summary.get("action"))
        if action in PASS_ACTIONS:
            ok, reason = _publisher_pr_checks_ok(result)
            if not ok:
                reason = "Publisher PASS rejected by structural contract: " + str(reason)
                summary.update(
                    {
                        "valid": True,
                        "status": "needs_fix",
                        "summary": reason,
                        "action": "NEED_FIX",
                        "risk_level": "medium",
                        "blocking": False,
                        "blocking_summary": [reason],
                    }
                )
                result.update(
                    {
                        "summary_status": "needs_fix",
                        "summary_action": "NEED_FIX",
                        "risk_level": "medium",
                        "blocking": False,
                        "publisher_pr_checks_contract_violation": True,
                        "publisher_pr_checks_contract_reason": reason,
                    }
                )

    if role == "scout":
        answer_markers = _scout_forbidden_markers(str(result.get("answer") or ""))
        summary_text = " ".join(str(summary.get(key) or "") for key in ("summary", "action", "status"))
        summary_markers = _scout_forbidden_markers(summary_text)
        if answer_markers:
            reason = (
                "Scout violated facts-only contract by including diagnostic/root-cause language: "
                + ", ".join(sorted(set(answer_markers)))
            )
            summary.update(
                {
                    "valid": True,
                    "status": "needs_fix",
                    "summary": reason,
                    "action": "NEED_FIX",
                    "risk_level": "medium",
                    "blocking": True,
                    "blocking_summary": [reason],
                }
            )
            result.update(
                {
                    "ok": False,
                    "summary_status": "needs_fix",
                    "summary_action": "NEED_FIX",
                    "risk_level": "medium",
                    "blocking": True,
                    "scout_facts_only_violation": True,
                    "scout_facts_only_forbidden_markers": sorted(set(answer_markers)),
                }
            )
        elif summary_markers:
            summary["summary"] = (
                "Scout completed a facts/context report. The auto-summary contained forbidden diagnostic wording "
                "and was sanitized; downstream roles must rely on factual evidence, relevant files, unknowns, "
                "and validation questions rather than Scout root-cause conclusions."
            )
            summary["action"] = normalize_action(summary.get("action") or result.get("summary_action") or "PASS")
            result["summary_action"] = summary["action"]
            result["scout_summary_sanitized"] = True
            result["scout_summary_forbidden_markers"] = sorted(set(summary_markers))

    return result


def _qa_validation_evidence_ok(qa_result: JsonDict) -> tuple[bool, str | None]:
    """Return whether a QA PASS has the minimum evidence required to unlock review/publish.

    QA may use extra summary keys because RoleSummary allows extra fields. v39
    requires build/test evidence plus a credible validation level. This prevents
    PASS from being unlocked by syntax-only checks when CI/runtime/build layout
    reconstruction was required but not attempted.
    """
    if not isinstance(qa_result, dict) or not _is_usable_role_result(qa_result):
        return False, "QA result is missing or not usable"
    summary = qa_result.get("summary") or {}
    if not isinstance(summary, dict):
        return False, "QA summary is missing"
    action = normalize_action(qa_result.get("summary_action") or summary.get("action"))
    if action not in PASS_ACTIONS:
        return False, f"QA action is not PASS: {action or 'missing'}"
    validation = summary.get("validation") or summary.get("validation_evidence") or _extract_answer_object(qa_result, "validation") or {}
    if not isinstance(validation, dict):
        return False, "QA summary/answer lacks validation evidence object"

    build_commands = validation.get("build_commands") or validation.get("compile_commands") or []
    test_commands = validation.get("test_commands") or validation.get("smoke_commands") or validation.get("integration_commands") or []
    build_ran = _truthy(validation.get("build_ran") or validation.get("compiled") or validation.get("compile_ran")) or _nonempty_list(build_commands)
    build_passed = _truthy(validation.get("build_passed") or validation.get("compile_passed") or validation.get("compiled_ok"))
    tests_run = _truthy(validation.get("tests_run") or validation.get("smoke_tests_run") or validation.get("integration_tests_run")) or _nonempty_list(test_commands)
    tests_passed = _truthy(validation.get("tests_passed") or validation.get("smoke_tests_passed") or validation.get("integration_tests_passed"))
    validation_level = str(validation.get("validation_level") or "").strip().lower()
    if not build_ran:
        return False, "QA did not report any compile/build command"
    if not build_passed:
        return False, "QA did not report successful compile/build"
    if not tests_run:
        return False, "QA did not report any targeted test/smoke/integration command"
    if not tests_passed:
        return False, "QA did not report successful targeted tests"
    if not validation_level:
        return False, "QA did not report validation_level"
    if validation_level in {"syntax_only", "syntax-level", "syntax", "not_validated", "none"}:
        return False, f"QA validation_level is not sufficient for PASS: {validation_level}"
    gaps = validation.get("validation_gaps") or []
    gap_items: list[str] = []
    if isinstance(gaps, list):
        gap_items.extend(str(g).lower() for g in gaps)
    elif gaps:
        gap_items.append(str(gaps).lower())
    # Also inspect summary/full answer text because some local LLMs fail to place
    # all gaps inside the structured validation object.
    gap_items.append(str(summary.get("summary") or "").lower())
    gap_items.append(str(qa_result.get("answer") or "").lower())
    gap_text = _strip_negative_validation_phrases(" ".join(gap_items))
    # Some gaps are risk annotations for Reviewer after real targeted evidence,
    # but gaps caused by missing installable validation tooling are blockers.
    # Example: "Ruby integration tests not run because Ruby/Bundler are not
    # installed" is not a non-blocking risk; QA must install Ruby/Bundler or
    # return NEED_FIX/BLOCKER after concrete install attempts. CI-listed suites
    # must not be deferred to "actual CI" just because the sandbox is missing a
    # runtime/package manager.
    disallowed_gap_markers = [
        "out of scope",
        "out-of-scope",
        "syntax-level",
        "syntax level",
        "syntax-only",
        "syntax only",
        "structurally correct",
        "structural correctness",
        "pattern matches",
        "core project is not present",
        "upstream project is not present",
        "host project is not present",
        "missing upstream",
        "missing host",
        "missing core",
        "required repository missing",
        "should be verified in the actual ci",
        "verified in the actual ci pipeline",
        "actual ci pipeline",
        "requires the full ci pipeline",
        "full ci pipeline",
        "cannot run in this sandbox",
        "cannot be validated locally",
        "cannot be validated locally without starting",
        "requires a live freeplane grpc server",
        "require a live freeplane grpc server",
        "requires a live freeplane instance",
        "require a live freeplane instance",
        "without freeplane_host",
        "freeplane_host environment variable",
        "excluded by default without freeplane_host",
        "xvfb, openbox, freeplane binary, grpc server startup",
        "ruby integration tests not run",
        "ruby tests not run",
        "bundler is not installed",
        "bundler not installed",
        "ruby is not installed",
        "ruby not installed",
        "not installed in the sandbox",
        "missing ruby",
        "missing bundler",
    ]
    if any(marker in gap_text for marker in disallowed_gap_markers):
        return False, "QA validation gaps indicate skipped required environment/build/runtime/tool validation"
    return True, None


def _reviewer_validation_review_ok(reviewer_result: JsonDict) -> tuple[bool, str | None]:
    """Return whether a Reviewer PASS is strong enough to unlock publishing."""
    if not isinstance(reviewer_result, dict) or not _is_usable_role_result(reviewer_result):
        return False, "Reviewer result is missing or not usable"
    summary = reviewer_result.get("summary") or {}
    if not isinstance(summary, dict):
        return False, "Reviewer summary is missing"
    action = normalize_action(reviewer_result.get("summary_action") or summary.get("action"))
    if action not in PASS_ACTIONS:
        return False, f"Reviewer action is not PASS: {action or 'missing'}"
    review = summary.get("validation_review") or summary.get("review_validation") or _extract_answer_object(reviewer_result, "validation_review")
    if not isinstance(review, dict):
        review = _synthesize_reviewer_validation_review_from_text(reviewer_result)
    if not isinstance(review, dict):
        return False, "Reviewer summary/answer lacks validation_review object"

    qa_build_ok = _truthy(review.get("qa_build_evidence_ok") or review.get("qa_build_ok"))
    qa_test_ok = _truthy(review.get("qa_test_evidence_ok") or review.get("qa_tests_ok"))
    qa_level_ok = _truthy(review.get("qa_validation_level_ok") or review.get("validation_level_ok"))
    syntax_rejected = _truthy(review.get("syntax_only_rejected") or review.get("syntax_only_not_accepted"))
    if not qa_build_ok:
        return False, "Reviewer did not confirm QA build evidence"
    if not qa_test_ok:
        return False, "Reviewer did not confirm QA test evidence"
    if not qa_level_ok:
        return False, "Reviewer did not confirm QA validation level was sufficient"
    if not syntax_rejected:
        return False, "Reviewer did not explicitly reject syntax-only validation for required CI/build/runtime tasks"
    gaps = review.get("validation_gaps") or []
    gap_text = ""
    if isinstance(gaps, list):
        gap_text = " ".join(str(g).lower() for g in gaps)
    elif gaps:
        gap_text = str(gaps).lower()
    gap_text = _strip_negative_validation_phrases(" ".join([
        gap_text,
        str(summary.get("summary") or "").lower(),
        str(reviewer_result.get("answer") or "").lower(),
    ]))
    reviewer_disallowed_markers = [
        "out of scope",
        "out-of-scope",
        "not validated",
        "syntax only",
        "syntax-only",
        "syntax-level",
        "structurally correct",
        "structural correctness",
        "pattern matches",
        "missing upstream",
        "missing core",
        "missing host",
        "should be verified in the actual ci",
        "actual ci pipeline",
        "requires the full ci pipeline",
        "cannot run in this sandbox",
        "cannot be validated locally",
        "freeplane_host environment variable",
        "without freeplane_host",
    ]
    if any(marker in gap_text for marker in reviewer_disallowed_markers):
        return False, "Reviewer validation_review gaps indicate skipped required validation"
    return True, None


def _latest_qa_result_for_current_coder_attempt(state: OpenHandsGraphState) -> JsonDict | None:
    """Return the latest QA result that validates the latest coder attempt.

    In retry cycles the history can contain ``qa NEED_FIX -> coder retry -> qa
    PASS``. Guards must use the QA result after the latest coder PASS, not an
    older QA result. If no coder is present (unit tests / custom flows), fall
    back to the latest QA result.
    """
    coder_idx = _latest_coder_pass_index(state)
    qa_after_coder = _latest_result_for_role_after_index(state, "qa", coder_idx)
    if qa_after_coder is not None:
        return qa_after_coder
    if coder_idx is not None:
        return None
    return _latest_result_for_role(state, "qa")


def _latest_qa_pass_index_for_current_coder_attempt(state: OpenHandsGraphState) -> tuple[int | None, JsonDict | None]:
    coder_idx = _latest_coder_pass_index(state)
    results = list(state.get("role_results") or [])
    for idx in range(len(results) - 1, -1, -1):
        if coder_idx is not None and idx <= coder_idx:
            break
        result = results[idx]
        if not isinstance(result, dict) or str(result.get("role") or "").lower() != "qa":
            continue
        ok, _ = _qa_validation_evidence_ok(result)
        if ok:
            return idx, result
        # Latest QA after the current coder attempt failed/needs fixes, so older
        # QA results must not unlock review/publish.
        return idx, result
    if coder_idx is None:
        idx, result = _latest_result_index_for_role(state, "qa")
        if result is not None:
            return idx, result
    return None, None


def _latest_reviewer_result_for_current_qa_validation(state: OpenHandsGraphState) -> JsonDict | None:
    """Return the reviewer result that reviewed the latest accepted QA pass."""
    qa_idx, qa_result = _latest_qa_pass_index_for_current_coder_attempt(state)
    qa_ok, _ = _qa_validation_evidence_ok(qa_result or {})
    if qa_ok:
        reviewer = _latest_result_for_role_after_index(state, "reviewer", qa_idx)
        if reviewer is not None:
            return reviewer
        return None
    return _latest_result_for_role(state, "reviewer")



def _role_action_pass(result: JsonDict | None) -> bool:
    if not _is_usable_role_result(result):
        return False
    summary = result.get("summary") if isinstance(result, dict) else {}
    action = normalize_action(result.get("summary_action") or (summary.get("action") if isinstance(summary, dict) else None))
    return action in PASS_ACTIONS


def _latest_pass_result_index_for_role_after(
    state: OpenHandsGraphState,
    role: str,
    after_index: int | None = None,
) -> tuple[int | None, JsonDict | None]:
    results = list(state.get("role_results") or [])
    for idx in range(len(results) - 1, -1, -1):
        if after_index is not None and idx <= after_index:
            break
        result = results[idx]
        if isinstance(result, dict) and str(result.get("role") or "").lower() == role and _role_action_pass(result):
            return idx, result
    if after_index is None:
        direct = state.get(f"{role}_result")
        if isinstance(direct, dict) and _role_action_pass(direct):
            return None, direct
    return None, None


def _decision_policy(decision: JsonDict) -> JsonDict:
    policy = decision.get("policy_evaluation")
    return policy if isinstance(policy, dict) else {}


def _report_id_exists(state: OpenHandsGraphState, report_id: str) -> bool:
    if not report_id:
        return False
    for result in list(state.get("role_results") or []):
        if isinstance(result, dict) and str(result.get("report_id") or "") == str(report_id):
            return True
        report = result.get("role_report") if isinstance(result, dict) else None
        if isinstance(report, dict) and str(report.get("report_id") or "") == str(report_id):
            return True
    return False


def _validate_accepted_report_ids(state: OpenHandsGraphState, decision: JsonDict) -> tuple[bool, str | None]:
    accepted = decision.get("accepted_report_ids")
    if not isinstance(accepted, dict):
        return True, None
    for key, value in accepted.items():
        if value is None or value == "":
            continue
        if not _report_id_exists(state, str(value)):
            return False, f"Team Lead referenced unknown accepted_report_ids.{key}: {value}"
    return True, None

def _has_qa_pass(state: OpenHandsGraphState) -> bool:
    ok, _ = _qa_pass_gate(state)
    return ok


def _last_specialist_result(state: OpenHandsGraphState) -> JsonDict | None:
    for result in reversed(list(state.get("role_results") or [])):
        if not isinstance(result, dict):
            continue
        role = str(result.get("role") or "").lower()
        if role and role != "team_lead":
            return result
    return None




SCOUT_FACTS_ONLY_INSTRUCTIONS = (
    "Collect factual context only for the original task. Extract exact CI/log evidence when present "
    "(failing job, step, command, error text, stack trace excerpt, failing test name, and visible environment details), "
    "inspect repository/workspace structure read-only, identify relevant files and why they are relevant, document existing patterns, "
    "document build/test/validation commands for later roles without running them, identify research domains, risks, unknowns, "
    "missing information, and validation questions. Do not propose causal explanations, diagnoses, or ranked causes."
)


def _enforce_scout_facts_only_decision(decision: TeamLeadDecision) -> TeamLeadDecision:
    """Force Scout assignments to be context-only even if Team Lead phrased them diagnostically.

    Direct Team Lead is tool-less, but it can still write bad instructions.
    Scout is a facts/context role, so LangGraph normalizes Scout instructions before
    they are injected into the OpenHands Scout conversation.
    """
    if str(decision.next_role or "").strip().lower() != "scout":
        return decision
    data = decision.model_dump(mode="python")
    data["instructions"] = SCOUT_FACTS_ONLY_INSTRUCTIONS
    if not data.get("context_sources"):
        data["context_sources"] = ["user_task", "repository", "workflow_history"]
    return TeamLeadDecision.model_validate(data).normalized()


def _publisher_pr_checks_ok(publisher_result: JsonDict | None) -> tuple[bool, str | None]:
    """Return whether Publisher reported completed successful PR checks.

    This is a structural contract check, not a repository-specific delivery
    policy. Publisher may create/find a PR, but it cannot report PASS without
    machine-readable pr_checks showing that gh discovered and waited for PR
    checks/statuses and that no failing/pending checks remain.
    """
    if not isinstance(publisher_result, dict) or not _is_usable_role_result(publisher_result):
        return False, "Publisher result is missing or not usable"
    summary = publisher_result.get("summary") or {}
    if not isinstance(summary, dict):
        return False, "Publisher summary is missing"
    action = normalize_action(publisher_result.get("summary_action") or summary.get("action"))
    if action not in PASS_ACTIONS:
        return False, f"Publisher action is not PASS: {action or 'missing'}"
    pr_checks = summary.get("pr_checks") or _extract_answer_object(publisher_result, "pr_checks") or {}
    if not isinstance(pr_checks, dict) or not pr_checks:
        return False, "Publisher PASS lacks pr_checks object"
    overall = str(pr_checks.get("overall_status") or pr_checks.get("status") or pr_checks.get("state") or "").strip().lower()
    if overall not in {"passed", "pass", "success", "successful"}:
        return False, f"Publisher pr_checks overall_status is not successful: {overall or 'missing'}"
    if not _truthy(pr_checks.get("waited")):
        return False, "Publisher did not report waiting for PR checks"
    publish = summary.get("publish") if isinstance(summary.get("publish"), dict) else {}
    head_sha = str(pr_checks.get("head_sha") or publish.get("head_sha") or "").strip()
    if not head_sha:
        return False, "Publisher did not report PR head SHA"
    failing = pr_checks.get("failing_checks") or []
    pending = pr_checks.get("pending_checks") or []
    if isinstance(failing, list) and any(str(item).strip() for item in failing):
        return False, "Publisher reported failing PR checks"
    if isinstance(pending, list) and any(str(item).strip() for item in pending):
        return False, "Publisher reported pending PR checks"
    check_runs = pr_checks.get("check_runs") or []
    commit_status = pr_checks.get("commit_status") or {}
    status_state = str(commit_status.get("state") or "").strip().lower() if isinstance(commit_status, dict) else ""
    has_check_runs = isinstance(check_runs, list) and len(check_runs) > 0
    has_success_status = status_state in {"success", "passed", "pass"}
    if not has_check_runs and not has_success_status:
        return False, "Publisher did not report any check runs or successful combined commit status"
    return True, None


def _latest_pass_result_for_role(state: OpenHandsGraphState, role: str) -> JsonDict | None:
    _, result = _latest_pass_result_index_for_role_after(state, role, None)
    return result


def _non_empty_string(value: Any) -> bool:
    return bool(str(value or "").strip())


def _scout_report_indicates_research_required(scout_result: JsonDict | None) -> bool:
    if not isinstance(scout_result, dict):
        return False
    report = scout_result.get("role_report") if isinstance(scout_result.get("role_report"), dict) else {}
    summary = scout_result.get("summary") if isinstance(scout_result.get("summary"), dict) else {}
    facts = report.get("facts") if isinstance(report.get("facts"), dict) else {}
    if report.get("research_required") is True or facts.get("research_required") is True:
        return True
    domains = report.get("research_domains") or facts.get("research_domains") or summary.get("research_domains")
    questions = report.get("research_questions") or facts.get("research_questions") or summary.get("research_questions")
    if isinstance(domains, (list, tuple)) and len(domains) > 0:
        return True
    if isinstance(questions, (list, tuple)) and len(questions) > 0:
        return True
    # Compatibility with older Scout reports that only nested domains under facts.
    nested_facts = summary.get("facts") if isinstance(summary.get("facts"), dict) else {}
    nested_domains = nested_facts.get("research_domains")
    nested_questions = nested_facts.get("research_questions")
    return bool(
        (isinstance(nested_domains, (list, tuple)) and nested_domains)
        or (isinstance(nested_questions, (list, tuple)) and nested_questions)
    )


def _research_waiver_ok(state: OpenHandsGraphState, decision: JsonDict) -> tuple[bool, str | None]:
    policy = _decision_policy(decision)
    if _role_action_pass(_latest_result_for_role(state, "research")):
        return True, None
    scout = _latest_pass_result_for_role(state, "scout")
    if not _scout_report_indicates_research_required(scout):
        return True, None
    if not _truthy(policy.get("can_skip_research")):
        return False, "Scout report indicates research is required, but Team Lead skipped research without policy_evaluation.can_skip_research=true"
    if not _non_empty_string(policy.get("skip_research_reason")):
        return False, "Team Lead set can_skip_research=true without skip_research_reason"
    # If a concrete scout report id is referenced, validate_accepted_report_ids already
    # checked it. This structural guard intentionally does not judge whether the
    # waiver is semantically correct.
    return True, None


def _architect_waiver_ok(state: OpenHandsGraphState, decision: JsonDict) -> tuple[bool, str | None]:
    if _role_action_pass(_latest_result_for_role(state, "architect")):
        return True, None
    policy = _decision_policy(decision)
    if not _truthy(policy.get("can_skip_architect")):
        return False, "Team Lead requested coder before architect PASS and without policy_evaluation.can_skip_architect=true"
    if not _non_empty_string(policy.get("skip_architect_reason")):
        return False, "Team Lead set can_skip_architect=true without skip_architect_reason"
    if not _role_action_pass(_latest_result_for_role(state, "senior_staff_engineer")):
        return False, "Team Lead requested coder with architect waiver before senior_staff_engineer produced a PASS strategy/report"
    accepted = decision.get("accepted_report_ids") if isinstance(decision.get("accepted_report_ids"), dict) else {}
    if not accepted.get("senior_staff_engineer"):
        return False, "Team Lead architect waiver must reference accepted_report_ids.senior_staff_engineer"
    return True, None

def _validate_team_lead_decision(state: OpenHandsGraphState, decision: JsonDict) -> tuple[bool, str | None]:
    action = normalize_action(decision.get("action"))
    if action == "STOP_COMPLETED":
        policy = _decision_policy(decision)
        if not _truthy(policy.get("can_complete")):
            return False, "Team Lead requested STOP_COMPLETED without policy_evaluation.can_complete=true"
        if not _truthy(policy.get("publisher_pr_checks_accepted")):
            return False, "Team Lead requested STOP_COMPLETED without policy_evaluation.publisher_pr_checks_accepted=true"
        publisher = _latest_result_for_role(state, "publisher")
        ok, reason = _publisher_pr_checks_ok(publisher)
        if not ok:
            return False, f"Team Lead requested STOP_COMPLETED before accepted publisher PR checks: {reason}"
        return True, None
    if action in {"STOP_BLOCKED", "ASK_HUMAN"}:
        return True, None
    if action not in TEAM_LEAD_RUN_ACTIONS:
        return False, f"Team Lead returned unsupported action: {action or 'missing'}"

    next_role = str(decision.get("next_role") or "").strip().lower()
    if next_role not in TEAM_LEAD_ALLOWED_ROLES:
        return False, f"Team Lead requested unsupported role: {next_role or 'missing'}"

    last_specialist = _last_specialist_result(state)
    if isinstance(last_specialist, dict) and last_specialist.get("ok") is False:
        failed_role = str(last_specialist.get("role") or "").lower()
        retryable = bool(last_specialist.get("retryable", True))
        allowed_after_failure = action == "RETRY_ROLE" and next_role == failed_role and retryable
        if not allowed_after_failure:
            return (
                False,
                f"Last specialist role {failed_role or 'unknown'} failed before producing a usable result; "
                "Team Lead must retry that role, ask human, stop blocked, or run a replacement only after explicit recovery policy.",
            )

    ids_ok, ids_reason = _validate_accepted_report_ids(state, decision)
    if not ids_ok:
        return False, ids_reason

    coder_idx = _latest_coder_pass_index(state)
    if next_role in {"senior_staff_engineer", "architect", "coder", "qa", "reviewer", "publisher"}:
        research_ok, research_reason = _research_waiver_ok(state, decision)
        if not research_ok:
            return False, research_reason

    if next_role == "publisher":
        qa_idx, qa_result = _latest_pass_result_index_for_role_after(state, "qa", coder_idx)
        if qa_result is None:
            return False, "Team Lead requested publisher before any QA PASS after the latest coder PASS"
        _, reviewer_result = _latest_pass_result_index_for_role_after(state, "reviewer", qa_idx)
        if reviewer_result is None:
            return False, "Team Lead requested publisher before any Reviewer PASS after the accepted QA PASS"
        policy = _decision_policy(decision)
        if not _truthy(policy.get("can_publish")):
            return False, "Team Lead requested publisher without explicit policy_evaluation.can_publish=true"
    if next_role == "reviewer":
        _, qa_result = _latest_pass_result_index_for_role_after(state, "qa", coder_idx)
        if qa_result is None:
            return False, "Team Lead requested reviewer before any QA PASS after the latest coder PASS"
    if next_role == "qa" and not _role_action_pass(_latest_result_for_role(state, "coder")):
        return False, "Team Lead requested QA before coder produced a PASS implementation/report"
    if next_role == "coder":
        architect_ok, architect_reason = _architect_waiver_ok(state, decision)
        if not architect_ok:
            return False, architect_reason
    return True, None


def _build_team_lead_runner(state: OpenHandsGraphState, config: Optional[RunnableConfig]) -> Any:
    cfg = _configurable(config)
    runner = cfg.get("team_lead_runner") or cfg.get("team_lead_decision_runner")
    if runner is not None:
        return runner
    base_url = (
        cfg.get("team_lead_base_url")
        or state.get("team_lead_base_url")
        or cfg.get("llm_base_url")
        or state.get("llm_base_url")
    )
    model = (
        cfg.get("team_lead_model")
        or state.get("team_lead_model")
        or cfg.get("openhands_default_model")
        or state.get("model")
    )
    api_key = (
        cfg.get("team_lead_api_key")
        or state.get("team_lead_api_key")
        or cfg.get("llm_api_key")
        or state.get("llm_api_key")
    )
    if not base_url:
        raise OpenHandsLangGraphError(
            "Team Lead workflow now uses a direct tool-less LLM call. Provide "
            "configurable.team_lead_base_url or CLI --team-lead-base-url "
            "(for example http://127.0.0.1:4000/v1)."
        )
    if not model:
        raise OpenHandsLangGraphError(
            "Team Lead workflow requires configurable.team_lead_model or CLI --team-lead-model/--model."
        )
    return DirectLLMTeamLeadRunner(
        base_url=str(base_url),
        model=str(model),
        api_key=str(api_key) if api_key else None,
        timeout=float(cfg.get("team_lead_timeout", state.get("team_lead_timeout", 120.0))),
        max_attempts=int(cfg.get("team_lead_max_attempts", state.get("team_lead_max_attempts", 3))),
        temperature=float(cfg.get("team_lead_temperature", state.get("team_lead_temperature", 0.0))),
    )


def _team_lead_result_from_decision(
    state: OpenHandsGraphState,
    *,
    decision: TeamLeadDecision,
    raw_response: str,
    attempts: int,
    started_at: str,
    duration_seconds: float,
    model: str | None = None,
) -> JsonDict:
    finished_at = _utc_now_iso()
    summary = decision.model_dump(mode="json")
    return {
        "role": "team_lead",
        "role_instance": "team_lead-1",
        "conversation_id": "direct-llm",
        "status": decision.status,
        "ok": True,
        "summary_status": decision.status,
        "summary_action": decision.action,
        "risk_level": decision.risk_level,
        "blocking": decision.blocking,
        "summary": summary,
        "summary_attempt_count": attempts,
        "summary_attempts": [],
        "answer": raw_response,
        "answer_run": {
            "text": raw_response,
            "status": "finished",
            "conversation_id": "direct-llm",
            "start": {"conversation_id": "direct-llm", "status": "READY"},
            "has_answer": bool(raw_response.strip()),
            "seen_event_count": 0,
        },
        "seen_event_count": 0,
        "team_lead_direct_llm": True,
        "metrics": {
            "role": "team_lead",
            "role_instance": "team_lead-1",
            "status": decision.status,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "summary_attempt_count": attempts,
            "answer_chars": len(raw_response or ""),
            "summary_chars": len(decision.summary or ""),
            "model": model,
            "direct_llm": True,
        },
    }


async def team_lead_node(state: OpenHandsGraphState, config: Optional[RunnableConfig] = None) -> OpenHandsGraphState:
    steps = int(state.get("team_lead_steps") or 0)
    max_steps = int(state.get("max_team_lead_steps") or 12)
    if steps >= max_steps:
        return {
            "next_node": "end",
            "final_status": "needs_human_review",
            "final_answer": f"Team Lead step limit reached ({steps}/{max_steps}).",
        }

    _trace_role_input("team_lead", state, config)
    ui = _workflow_ui(config)
    prompt = build_team_lead_decision_prompt({**state, "team_lead_steps": steps, "max_team_lead_steps": max_steps})
    if ui is not None:
        try:
            ui.team_lead_decision_prompt(prompt, state={**state, "team_lead_steps": steps, "max_team_lead_steps": max_steps})
        except Exception:
            pass
    started_at = _utc_now_iso()
    started_monotonic = time.monotonic()
    try:
        runner = _build_team_lead_runner(state, config)
        direct_result = await runner.decide(prompt=prompt)
        decision = _enforce_scout_facts_only_decision(direct_result.decision.normalized())
        duration_seconds = _round_seconds(time.monotonic() - started_monotonic)
        result_dict = _team_lead_result_from_decision(
            state,
            decision=decision,
            raw_response=getattr(direct_result, "raw_response", decision.model_dump_json()),
            attempts=int(getattr(direct_result, "attempts", 1)),
            started_at=started_at,
            duration_seconds=duration_seconds,
            model=getattr(direct_result, "model", None),
        )
    except Exception as exc:
        duration_seconds = _round_seconds(time.monotonic() - started_monotonic)
        failed_result = _synthetic_failed_role_result(
            state,
            role="team_lead",
            role_instance="team_lead-1",
            error=exc,
            started_at=started_at,
            duration_seconds=duration_seconds,
            persistent_session=False,
        )
        _trace_role_result("team_lead", failed_result, config)
        if ui is not None:
            try:
                ui.team_lead_decision_result(failed_result)
            except Exception:
                pass
        errors = list(state.get("errors") or [])
        errors.append(f"team_lead: {exc}")
        role_results = list(state.get("role_results") or [])
        role_results.append(failed_result)
        return {
            "role_results": role_results,
            "team_lead_result": failed_result,
            "last_role_result": failed_result,
            "last_role_metrics": failed_result["metrics"],
            "team_lead_steps": steps + 1,
            "next_node": "end",
            "final_status": "needs_human_review",
            "final_answer": f"Team Lead direct LLM decision failed: {exc}",
            "errors": errors,
        }

    _trace_role_result("team_lead", result_dict, config)
    if ui is not None:
        try:
            ui.team_lead_decision_result(result_dict)
        except Exception:
            pass
    ok, error = _validate_team_lead_decision(state, decision.model_dump(mode="json"))

    role_results = list(state.get("role_results") or [])
    role_results.append(result_dict)
    patch: OpenHandsGraphState = {
        "role_results": role_results,
        "team_lead_result": result_dict,
        "last_role_result": result_dict,
        "last_role_metrics": result_dict["metrics"],
        "team_lead_decision": decision.model_dump(mode="json"),
        "team_lead_steps": steps + 1,
        "final_answer": decision.summary,
    }

    if not ok:
        errors = list(state.get("errors") or [])
        errors.append(error or "Invalid Team Lead decision")
        patch["errors"] = errors
        patch["next_node"] = "end"
        patch["final_status"] = "needs_human_review"
        patch["final_answer"] = error or "Invalid Team Lead decision"
        return patch

    action = normalize_action(decision.action)
    if action in TEAM_LEAD_RUN_ACTIONS:
        role = str(decision.next_role or "").strip().lower()
        role_instance = decision.role_instance or f"{role}-1"
        patch["pending_role"] = role
        patch["pending_role_instance"] = str(role_instance)
        patch["next_node"] = "role_executor"
        patch["final_status"] = "team_lead_selected_role"
        patch["final_answer"] = f"Team Lead selected {action} {role_instance}."
        return patch

    patch["next_node"] = "end"
    if action == "STOP_COMPLETED":
        patch["final_status"] = "completed"
    elif action == "STOP_BLOCKED":
        patch["final_status"] = "blocked"
    else:
        patch["final_status"] = "needs_human_review"
    patch["final_answer"] = decision.reason or decision.summary or f"Team Lead stopped with action {action}."
    return patch


async def dynamic_role_executor_node(state: OpenHandsGraphState, config: Optional[RunnableConfig] = None) -> OpenHandsGraphState:
    role = str(state.get("pending_role") or "").strip().lower()
    if not role:
        return _append_error(state, "No pending_role selected by Team Lead")
    role_instance = state.get("pending_role_instance") or f"{role}-1"
    prompt = build_role_prompt(role, state)
    return await _run_role_with_prompt(
        state,
        config,
        role=role,
        role_instance=str(role_instance),
        prompt=prompt,
        summary_instructions=build_role_summary_instructions(role),
        persistent_session=True,
    )


def route_after_team_lead(state: OpenHandsGraphState) -> str:
    return "role_executor" if state.get("next_node") == "role_executor" else "end"


def review_decision_node(state: OpenHandsGraphState) -> OpenHandsGraphState:
    """Decide the next stage after reviewer.

    This node is intentionally deterministic. The reviewer LLM provides a
    structured summary action, but LangGraph owns the routing decision.
    """
    if state.get("errors"):
        return {"next_node": "end", "final_status": "failed"}

    reviewer_result = state.get("reviewer_result") or state.get("last_role_result") or {}
    action = normalize_action(reviewer_result.get("summary_action") or (reviewer_result.get("summary") or {}).get("action"))
    current_iteration = int(state.get("current_iteration") or 0)
    max_fix_iterations = int(state.get("max_fix_iterations") if state.get("max_fix_iterations") is not None else 2)

    if action in PASS_ACTIONS:
        ok, reason = _reviewer_validation_review_ok(reviewer_result)
        if not ok:
            return {
                "next_node": "end",
                "final_status": "needs_human_review",
                "final_answer": f"Reviewer returned PASS without required QA/lint/environment validation review evidence: {reason}",
            }
        return {
            "next_node": "publisher",
            "final_status": "ready_to_publish",
            "final_answer": "Reviewer returned PASS with QA/lint/environment validation review evidence; routing to Publisher.",
        }

    if action in NEED_FIX_ACTIONS:
        if current_iteration < max_fix_iterations:
            return {
                "next_node": "coder",
                "current_iteration": current_iteration + 1,
                "final_status": "needs_fix",
            }
        return {
            "next_node": "end",
            "final_status": "needs_human_review",
            "final_answer": "Reviewer still requested fixes after max_fix_iterations.",
        }

    if action in BLOCK_ACTIONS or reviewer_result.get("blocking") is True:
        return {
            "next_node": "end",
            "final_status": "blocked",
            "final_answer": "Development workflow blocked by reviewer.",
        }

    return {
        "next_node": "end",
        "final_status": "needs_human_review",
        "final_answer": f"Reviewer action was ambiguous: {action}",
    }


def route_after_senior_staff(state: OpenHandsGraphState) -> str:
    return "architect" if state.get("next_node") == "architect" else "end"




def route_after_qa(state: OpenHandsGraphState) -> str:
    next_node = state.get("next_node")
    if next_node == "coder":
        return "coder"
    if next_node == "reviewer":
        return "reviewer"
    return "end"


def route_after_review(state: OpenHandsGraphState) -> str:
    next_node = state.get("next_node")
    if next_node == "coder":
        return "coder"
    if next_node == "publisher":
        return "publisher"
    return "end"


def route_continue_or_end(next_node: str):
    def _route(state: OpenHandsGraphState) -> str:
        return "end" if state.get("errors") else next_node

    return _route
