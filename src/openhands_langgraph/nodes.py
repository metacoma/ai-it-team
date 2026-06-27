from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Optional

try:
    from langchain_core.runnables import RunnableConfig
except ImportError:  # pragma: no cover - LangGraph is an optional extra.
    RunnableConfig = dict[str, Any]  # type: ignore[misc,assignment]

from openhands import AppConversationStart, OpenHandsInstance, OpenHandsRoleRunner

from .prompts import (
    BLOCK_ACTIONS,
    NEED_FIX_ACTIONS,
    PASS_ACTIONS,
    TEAM_LEAD_ALLOWED_ROLES,
    TEAM_LEAD_RUN_ACTIONS,
    TEAM_LEAD_STOP_ACTIONS,
    build_role_prompt,
    build_role_summary_instructions,
    build_team_lead_decision_prompt,
    normalize_action,
    role_input_summary,
)
from .reports import parse_role_report, report_required_target_gaps
from .state import JsonDict, OpenHandsGraphState
from .team_lead import DirectLLMTeamLeadRunner, TeamLeadDecision, TeamLeadDecisionResult


class OpenHandsLangGraphError(RuntimeError):
    """Configuration/runtime error raised by the LangGraph integration layer."""


_COLOR = {
    "reset": "\033[0m",
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


SCOUT_FACTS_ONLY_INSTRUCTIONS = (
    "Scout must collect factual repository/workspace context only. "
    "Do not ask Scout for root-cause hypotheses, solutions, plans, fixes, or validation execution."
)


# ---------------------------------------------------------------------------
# Generic runtime helpers
# ---------------------------------------------------------------------------


def _resolve_role_model(role: str, state: OpenHandsGraphState) -> str | None:
    role_models = state.get("role_models")
    if isinstance(role_models, dict):
        model = role_models.get(role)
        if isinstance(model, str) and model.strip():
            return model.strip()
    return state.get("model")


def _configurable(config: Optional[RunnableConfig]) -> JsonDict:
    if config is None:
        return {}
    if isinstance(config, dict):
        value = config.get("configurable", {})
        return value if isinstance(value, dict) else {}
    value = getattr(config, "configurable", {})
    return value if isinstance(value, dict) else {}


def _graph_trace_enabled(config: Optional[RunnableConfig]) -> bool:
    return bool(_configurable(config).get("openhands_graph_trace", False))


def _graph_trace_color(config: Optional[RunnableConfig]) -> bool:
    return bool(_configurable(config).get("openhands_graph_color", True))


def _c(text: str, color: str, config: Optional[RunnableConfig]) -> str:
    if not _graph_trace_color(config):
        return text
    return f"{_COLOR.get(color, '')}{text}{_COLOR['reset']}"


def _short(value: Any, limit: int = 240) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text[: limit - 3] + "..." if len(text) > limit else text


def _trace_role_input(role: str, state: OpenHandsGraphState, config: Optional[RunnableConfig]) -> None:
    if not _graph_trace_enabled(config):
        return
    role_key = (role or "role").lower()
    print(_c(f"▶ {role_key.upper()} input", role_key, config))
    for line in role_input_summary(role_key, state):
        print(f" {_c('•', 'dim', config)} {line}")


def _trace_role_result(role: str, result_dict: JsonDict, config: Optional[RunnableConfig]) -> None:
    if not _graph_trace_enabled(config):
        return
    role_key = (role or "role").lower()
    summary = result_dict.get("summary") if isinstance(result_dict.get("summary"), dict) else {}
    action = result_dict.get("summary_action") or summary.get("action") or ""
    status = result_dict.get("summary_status") or summary.get("status") or result_dict.get("status") or ""
    risk = result_dict.get("risk_level") or summary.get("risk_level") or ""
    blocking = result_dict.get("blocking") if result_dict.get("blocking") is not None else summary.get("blocking")
    print(_c(f"✓ {role_key.upper()} result", "ok" if result_dict.get("ok") else "error", config))
    print(f" {_c('•', 'dim', config)} status: {status or 'unknown'}")
    print(f" {_c('•', 'dim', config)} action: {action or 'unknown'}")
    print(f" {_c('•', 'dim', config)} risk: {risk or 'unknown'}")
    print(f" {_c('•', 'dim', config)} blocking: {blocking}")
    if summary.get("summary"):
        print(f" {_c('•', 'dim', config)} summary: {_short(summary.get('summary'))}")
    if result_dict.get("conversation_id"):
        print(f" {_c('•', 'dim', config)} conversation: {result_dict.get('conversation_id')}")


def _workflow_ui(config: Optional[RunnableConfig]) -> Any:
    return _configurable(config).get("openhands_workflow_ui")


def _append_error(state: OpenHandsGraphState, error: str) -> OpenHandsGraphState:
    errors = list(state.get("errors") or [])
    errors.append(error)
    return {"errors": errors, "final_status": "failed", "last_role_result": None}


def _drop_recovered_role_errors(errors: list[str], role: str) -> list[str]:
    prefix = f"{str(role or '').strip().lower()}:"
    if not prefix or prefix == ":":
        return errors
    return [error for error in errors if not str(error).strip().lower().startswith(prefix)]


def _build_runner(state: OpenHandsGraphState, config: Optional[RunnableConfig]) -> OpenHandsRoleRunner:
    cfg = _configurable(config)
    runner = cfg.get("openhands_runner")
    if runner is not None and hasattr(runner, "run_role"):
        return runner

    instance = cfg.get("openhands_instance")
    if instance is None:
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
    default_summary = getattr(OpenHandsRoleRunner(instance), "summary_instructions", None)
    return OpenHandsRoleRunner(
        instance,
        summary_instructions=cfg.get("summary_instructions") or default_summary,
        summary_max_attempts=int(cfg.get("summary_max_attempts", 0)),
    )


def _include_answer(config: Optional[RunnableConfig]) -> bool:
    return bool(_configurable(config).get("include_answer_in_state", True))


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


def _base_run_options(state: OpenHandsGraphState, config: Optional[RunnableConfig]) -> JsonDict:
    cfg = _configurable(config)
    run_options: JsonDict = {}
    run_options.update(cfg.get("openhands_run_options") or {})
    run_options.update(state.get("role_run_options") or {})
    return run_options


def _role_state_key(role: str) -> str:
    role = (role or "role").lower()
    if role in TEAM_LEAD_ALLOWED_ROLES or role == "team_lead":
        return f"{role}_result"
    return "last_role_result"


def _role_conversation_title(role: str, state: OpenHandsGraphState) -> str:
    task = str(state.get("user_task") or state.get("prompt") or "OpenHands task").replace("\n", " ").strip()
    task = " ".join(task.split())
    if len(task) > 96:
        task = task[:93].rstrip() + "..."
    return f"{(role or 'role').strip()}: {task}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _round_seconds(value: float) -> float:
    return round(max(0.0, value), 3)


def _session_key(role: str, role_instance: str | None) -> str:
    return role_instance or f"{(role or 'role').lower()}-1"


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
        "known_event_ids": sorted(getattr(result, "seen_event_ids", frozenset()) or []),
        "known_event_count": len(getattr(result, "seen_event_ids", frozenset()) or []),
    }
    return sessions


# ---------------------------------------------------------------------------
# Role result parsing / evidence helpers
# ---------------------------------------------------------------------------


def _classify_role_failure(error: BaseException | str) -> tuple[str, bool]:
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
    conversation_id = session.get("conversation_id") if isinstance(session, dict) else ""
    finished_at = _utc_now_iso()
    summary = {
        "valid": True,
        "status": "failed",
        "summary": f"{role} runtime failure before producing a usable assistant answer/report ({error_type}).",
        "action": "FAILED",
        "risk_level": "high",
        "blocking": True,
        "blocking_summary": [error_text],
    }
    return {
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


def _summary_dict(result: JsonDict | None) -> JsonDict:
    summary = (result or {}).get("summary")
    return summary if isinstance(summary, dict) else {}


def _summary_action(result: JsonDict | None) -> str:
    if not isinstance(result, dict):
        return ""
    summary = _summary_dict(result)
    return normalize_action(result.get("summary_action") or summary.get("action"))


def _role_action_pass(result: JsonDict | None) -> bool:
    return _is_usable_role_result(result) and _summary_action(result) in PASS_ACTIONS


def _is_usable_role_result(result: JsonDict | None) -> bool:
    if not isinstance(result, dict) or not result:
        return False
    if result.get("ok") is not True:
        return False
    if _summary_action(result) in BLOCK_ACTIONS:
        return False
    return bool(str(result.get("answer") or "").strip() or result.get("summary"))


def _latest_result_for_role(state: OpenHandsGraphState, role: str) -> JsonDict | None:
    for result in reversed(list(state.get("role_results") or [])):
        if isinstance(result, dict) and str(result.get("role") or "").lower() == role:
            return result
    direct = state.get(f"{role}_result")
    return direct if isinstance(direct, dict) and direct else None


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


def _latest_pass_result_for_role(state: OpenHandsGraphState, role: str) -> JsonDict | None:
    for result in reversed(list(state.get("role_results") or [])):
        if isinstance(result, dict) and str(result.get("role") or "").lower() == role and _role_action_pass(result):
            return result
    direct = state.get(f"{role}_result")
    return direct if _role_action_pass(direct if isinstance(direct, dict) else None) else None


def _latest_pass_result_for_role_after_index(
    state: OpenHandsGraphState,
    role: str,
    after_index: int | None,
) -> JsonDict | None:
    result = _latest_result_for_role_after_index(state, role, after_index)
    return result if _role_action_pass(result) else None


def _latest_coder_pass_index(state: OpenHandsGraphState) -> int | None:
    results = list(state.get("role_results") or [])
    for idx in range(len(results) - 1, -1, -1):
        result = results[idx]
        if isinstance(result, dict) and str(result.get("role") or "").lower() == "coder" and _role_action_pass(result):
            return idx
    direct = state.get("coder_result")
    if _role_action_pass(direct if isinstance(direct, dict) else None):
        return None
    return None


def _latest_coder_pass_result(state: OpenHandsGraphState) -> JsonDict | None:
    idx = _latest_coder_pass_index(state)
    if idx is not None:
        results = list(state.get("role_results") or [])
        if 0 <= idx < len(results) and isinstance(results[idx], dict):
            return results[idx]
    direct = state.get("coder_result")
    return direct if _role_action_pass(direct if isinstance(direct, dict) else None) else None


def _iter_json_objects_from_text(text: str) -> list[JsonDict]:
    if not text:
        return []
    objects: list[JsonDict] = []
    for start, ch in enumerate(text):
        if ch != "{":
            continue
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            current = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif current == "\\":
                    escape = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
                continue
            if current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : idx + 1])
                    except Exception:
                        break
                    if isinstance(parsed, dict):
                        objects.append(parsed)
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


def _postprocess_role_result(role: str, result_dict: JsonDict) -> JsonDict:
    summary = _summary_dict(result_dict)
    role_instance = result_dict.get("role_instance")
    fallback_report_id = (
        result_dict.get("report_id")
        or f"{role_instance or role}:{result_dict.get('conversation_id') or result_dict.get('summary_attempt_count') or 'result'}"
    )
    report, source = parse_role_report(
        role,
        answer=str(result_dict.get("answer") or ""),
        summary=summary,
        role_instance=str(role_instance) if role_instance else None,
        fallback_report_id=str(fallback_report_id),
    )
    if report:
        report.setdefault("report_id", str(fallback_report_id))
        result_dict["role_report"] = report
        result_dict["role_report_source"] = source
        result_dict["report_id"] = report.get("report_id") or str(fallback_report_id)
        if isinstance(report.get("validation_profile"), dict) and report.get("validation_profile"):
            summary.setdefault("validation_profile", report.get("validation_profile"))
        for key in ("validation", "validation_review", "pr_checks", "publish", "files_changed", "routing_hints"):
            if key in report and report.get(key) not in (None, [], {}):
                summary.setdefault(key, report.get(key))
    else:
        result_dict.setdefault("report_id", str(fallback_report_id))

    # Recover structured evidence from answer prose when the compact summary lost it.
    if role == "qa" and not isinstance(summary.get("validation"), dict):
        validation = _extract_answer_object(result_dict, "validation")
        if validation:
            summary["validation"] = validation
    elif role == "reviewer" and not isinstance(summary.get("validation_review"), dict):
        validation_review = _extract_answer_object(result_dict, "validation_review")
        if validation_review:
            summary["validation_review"] = validation_review
    elif role == "publisher" and not isinstance(summary.get("pr_checks"), dict):
        pr_checks = _extract_answer_object(result_dict, "pr_checks")
        if pr_checks:
            summary["pr_checks"] = pr_checks

    result_dict["summary"] = summary
    if role == "qa" and isinstance(summary.get("validation"), dict):
        gaps = report_required_target_gaps(summary.get("validation_profile"), summary.get("validation"))
        if gaps:
            summary["validation"].setdefault("profile_gaps", gaps)
    return result_dict


def _role_report_validation_profile(result_dict: JsonDict) -> JsonDict | None:
    report = result_dict.get("role_report")
    if isinstance(report, dict) and isinstance(report.get("validation_profile"), dict) and report.get("validation_profile"):
        return report["validation_profile"]
    summary = result_dict.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("validation_profile"), dict) and summary.get("validation_profile"):
        return summary["validation_profile"]
    return None


# ---------------------------------------------------------------------------
# OpenHands role execution nodes
# ---------------------------------------------------------------------------


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
    summary_attempts = getattr(result, "summary_attempts", None) or result_dict.get("summary_attempts") or []
    answer = getattr(result, "answer", result_dict.get("answer") or "") or ""
    summary_text = getattr(result, "summary_text", "") or ""
    result_dict["metrics"] = {
        "role": role,
        "role_instance": role_instance,
        "started_at": started_at,
        "finished_at": _utc_now_iso(),
        "duration_seconds": duration_seconds,
        "summary_attempt_count": result_dict.get("summary_attempt_count", len(summary_attempts)),
        "answer_chars": len(answer),
        "summary_chars": len(summary_text),
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
    updated_sessions = (
        _update_role_session_from_result(state, role=role, role_instance=role_instance, result=result)
        if persistent_session
        else state.get("role_sessions")
    )
    patch: OpenHandsGraphState = {
        "role_results": role_results,
        "last_role_result": result_dict,
        "last_role_metrics": result_dict["metrics"],
        "final_answer": answer,
        "final_status": "completed" if result_dict.get("ok") else "failed",
        "errors": errors,
    }
    validation_profile = _role_report_validation_profile(result_dict)
    if validation_profile:
        patch["validation_profile"] = validation_profile
    if updated_sessions is not None:
        patch["role_sessions"] = updated_sessions
    patch[_role_state_key(role)] = result_dict  # type: ignore[literal-required]
    return patch


async def run_openhands_role_node(
    state: OpenHandsGraphState,
    config: Optional[RunnableConfig] = None,
) -> OpenHandsGraphState:
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


async def senior_staff_engineer_node(
    state: OpenHandsGraphState,
    config: Optional[RunnableConfig] = None,
) -> OpenHandsGraphState:
    return await _run_role_with_prompt(
        state,
        config,
        role="senior_staff_engineer",
        role_instance="senior_staff_engineer-1",
        prompt=build_role_prompt("senior_staff_engineer", state),
        summary_instructions=build_role_summary_instructions("senior_staff_engineer"),
    )


def senior_staff_decision_node(state: OpenHandsGraphState) -> OpenHandsGraphState:
    if state.get("errors"):
        return {"next_node": "end", "final_status": "failed"}
    staff_result = state.get("senior_staff_engineer_result") or state.get("last_role_result") or {}
    action = _summary_action(staff_result if isinstance(staff_result, dict) else None)
    if action in PASS_ACTIONS or action in {"PROCEED", "PROCEED_TO_ARCHITECT", "STRATEGY_READY"}:
        return {
            "next_node": "architect",
            "final_status": "strategy_ready",
            "final_answer": "Senior Staff returned an execution contract and strategy; routing to Architect.",
        }
    if action in NEED_FIX_ACTIONS or action in {"NEED_MORE_RESEARCH", "NEED_MORE_SCOUT", "ASK_HUMAN"}:
        return {
            "next_node": "end",
            "final_status": "needs_human_review",
            "final_answer": f"Senior Staff requested additional input before architecture: {action}",
        }
    if action in BLOCK_ACTIONS or (isinstance(staff_result, dict) and staff_result.get("blocking") is True):
        return {
            "next_node": "end",
            "final_status": "blocked",
            "final_answer": "Development workflow blocked by Senior Staff execution contract gate.",
        }
    return {"next_node": "end", "final_status": "needs_human_review", "final_answer": f"Senior Staff action was ambiguous: {action}"}


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
    action = _summary_action(publisher_result if isinstance(publisher_result, dict) else None)
    if action in PASS_ACTIONS:
        patch["final_status"] = "completed"
        patch["final_answer"] = "Development workflow completed: Publisher pushed changes and created or found a pull request."
    elif action in NEED_FIX_ACTIONS:
        patch["final_status"] = "needs_human_review"
        patch["final_answer"] = "Publisher requested fixes after reviewer PASS; human review is required before retrying."
    elif action in BLOCK_ACTIONS or (isinstance(publisher_result, dict) and publisher_result.get("blocking") is True):
        patch["final_status"] = "publish_blocked"
        patch["final_answer"] = "Development workflow blocked by Publisher during push/PR creation."
    return patch


# ---------------------------------------------------------------------------
# Stage 2 deterministic gates
# ---------------------------------------------------------------------------


def _validation_from_result(result: JsonDict | None) -> JsonDict:
    if not isinstance(result, dict):
        return {}
    summary = _summary_dict(result)
    for candidate in (
        summary.get("validation"),
        (result.get("role_report") or {}).get("validation") if isinstance(result.get("role_report"), dict) else None,
        _extract_answer_object(result, "validation"),
    ):
        if isinstance(candidate, dict):
            return candidate
    return {}


def _review_validation_from_result(result: JsonDict | None) -> JsonDict:
    if not isinstance(result, dict):
        return {}
    summary = _summary_dict(result)
    for candidate in (
        summary.get("validation_review"),
        (result.get("role_report") or {}).get("validation_review") if isinstance(result.get("role_report"), dict) else None,
        _extract_answer_object(result, "validation_review"),
    ):
        if isinstance(candidate, dict):
            return candidate
    return {}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1", "pass", "passed", "ok", "success", "accepted"}
    return bool(value)


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and any(str(item).strip() for item in value)


def _qa_validation_evidence_ok(qa_result: JsonDict | None) -> tuple[bool, str | None]:
    if not _role_action_pass(qa_result):
        return False, "QA did not return a usable PASS result"
    validation = _validation_from_result(qa_result)
    summary_text = str(_summary_dict(qa_result).get("summary") or qa_result.get("answer") or "").lower() if isinstance(qa_result, dict) else ""
    level = str(validation.get("validation_level") or "").strip().lower()
    overall = str(validation.get("overall_status") or "").strip().lower()

    if level in {"not_applicable", "not-applicable", "not applicable", "n/a", "na"}:
        if "not applicable" in summary_text or "no meaningful validation" in summary_text or validation.get("reason"):
            return True, None
        return False, "QA marked validation not_applicable without a concrete reason"

    if validation.get("profile_gaps") or validation.get("blocking_gaps"):
        return False, "QA validation contains profile/blocking gaps"

    build_ran = _truthy(validation.get("build_ran"))
    build_passed = _truthy(validation.get("build_passed"))
    tests_run = _truthy(validation.get("tests_run"))
    tests_passed = _truthy(validation.get("tests_passed"))
    if build_ran and build_passed and tests_run and tests_passed:
        if level in {"", "syntax_only", "syntax-only", "not_validated", "not-validated"}:
            return False, f"QA validation_level is too weak: {level or 'missing'}"
        return True, None

    if overall in {"passed", "pass", "ok", "success"} and _nonempty_list(validation.get("targets")):
        bad_targets: list[Any] = []
        for target in validation.get("targets") or []:
            if not isinstance(target, dict):
                continue
            required = target.get("required")
            if required is None:
                required = bool(target.get("required_by"))
            status = str(target.get("status") or "").strip().lower()
            if required and status not in {"passed", "pass", "ok", "success"}:
                bad_targets.append(target)
        if not bad_targets:
            return True, None
        return False, "QA validation has required targets that did not pass"

    return False, "QA PASS lacks build/test/target evidence"


def _reviewer_validation_review_ok(reviewer_result: JsonDict | None) -> tuple[bool, str | None]:
    if not _role_action_pass(reviewer_result):
        return False, "Reviewer did not return a usable PASS result"
    validation_review = _review_validation_from_result(reviewer_result)
    if _truthy(validation_review.get("qa_skip_accepted")):
        reason = validation_review.get("qa_skip_reason") or validation_review.get("reason")
        return (True, None) if _non_empty_string(reason) else (False, "Reviewer accepted QA skip without a reason")
    if not validation_review:
        return False, "Reviewer PASS lacks validation_review evidence"
    fields = ["qa_build_evidence_ok", "qa_test_evidence_ok", "qa_validation_level_ok"]
    if all(_truthy(validation_review.get(field)) for field in fields):
        if validation_review.get("validation_gaps"):
            return False, "Reviewer validation_review lists validation gaps"
        return True, None
    return False, "Reviewer did not accept QA build/test/validation-level evidence"


def qa_decision_node(state: OpenHandsGraphState) -> OpenHandsGraphState:
    if state.get("errors"):
        return {"next_node": "end", "final_status": "failed"}
    qa_result = state.get("qa_result") or state.get("last_role_result") or {}
    action = _summary_action(qa_result if isinstance(qa_result, dict) else None)
    current_iteration = int(state.get("current_iteration") or 0)
    max_fix_iterations = int(state.get("max_fix_iterations") if state.get("max_fix_iterations") is not None else 2)
    if action in PASS_ACTIONS:
        ok, reason = _qa_validation_evidence_ok(qa_result if isinstance(qa_result, dict) else None)
        if not ok:
            return {
                "next_node": "end",
                "final_status": "needs_human_review",
                "final_answer": f"QA returned PASS without acceptable validation evidence: {reason}",
            }
        return {"next_node": "reviewer", "final_status": "qa_passed", "final_answer": "QA returned PASS; routing to Reviewer."}
    if action in NEED_FIX_ACTIONS:
        if current_iteration < max_fix_iterations:
            return {"next_node": "coder", "current_iteration": current_iteration + 1, "final_status": "needs_fix", "final_answer": "QA requested fixes; routing back to Coder."}
        return {"next_node": "end", "final_status": "needs_human_review", "final_answer": "QA still requested fixes after max_fix_iterations."}
    if action in BLOCK_ACTIONS or (isinstance(qa_result, dict) and qa_result.get("blocking") is True):
        return {"next_node": "end", "final_status": "blocked", "final_answer": "Development workflow blocked by QA validation."}
    return {"next_node": "end", "final_status": "needs_human_review", "final_answer": f"QA action was ambiguous: {action}"}


def review_decision_node(state: OpenHandsGraphState) -> OpenHandsGraphState:
    if state.get("errors"):
        return {"next_node": "end", "final_status": "failed"}
    reviewer_result = state.get("reviewer_result") or state.get("last_role_result") or {}
    action = _summary_action(reviewer_result if isinstance(reviewer_result, dict) else None)
    current_iteration = int(state.get("current_iteration") or 0)
    max_fix_iterations = int(state.get("max_fix_iterations") if state.get("max_fix_iterations") is not None else 2)
    if action in PASS_ACTIONS:
        ok, reason = _reviewer_validation_review_ok(reviewer_result if isinstance(reviewer_result, dict) else None)
        if not ok:
            return {
                "next_node": "end",
                "final_status": "needs_human_review",
                "final_answer": f"Reviewer returned PASS without acceptable review evidence: {reason}",
            }
        return {"next_node": "publisher", "final_status": "review_passed", "final_answer": "Reviewer returned PASS; routing to Publisher."}
    if action in NEED_FIX_ACTIONS:
        if current_iteration < max_fix_iterations:
            return {"next_node": "coder", "current_iteration": current_iteration + 1, "final_status": "needs_fix", "final_answer": "Reviewer requested fixes; routing back to Coder."}
        return {"next_node": "end", "final_status": "needs_human_review", "final_answer": "Reviewer still requested fixes after max_fix_iterations."}
    if action in BLOCK_ACTIONS or (isinstance(reviewer_result, dict) and reviewer_result.get("blocking") is True):
        return {"next_node": "end", "final_status": "blocked", "final_answer": "Development workflow blocked by Reviewer."}
    return {"next_node": "end", "final_status": "needs_human_review", "final_answer": f"Reviewer action was ambiguous: {action}"}


# ---------------------------------------------------------------------------
# Team Lead policy validation / flexible routing
# ---------------------------------------------------------------------------


def _decision_policy(decision: TeamLeadDecision) -> JsonDict:
    value = decision.policy_evaluation
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="python")
        return dumped if isinstance(dumped, dict) else {}
    return value if isinstance(value, dict) else {}


def _accepted_report_ids(decision: TeamLeadDecision) -> JsonDict:
    value = decision.accepted_report_ids
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="python")
        return dumped if isinstance(dumped, dict) else {}
    return value if isinstance(value, dict) else {}


def _report_id_for_result(result: JsonDict | None) -> str | None:
    if not isinstance(result, dict):
        return None
    report_id = result.get("report_id")
    if report_id:
        return str(report_id)
    report = result.get("role_report")
    if isinstance(report, dict) and report.get("report_id"):
        return str(report.get("report_id"))
    return None


def _report_id_exists(state: OpenHandsGraphState, report_id: str) -> bool:
    for result in list(state.get("role_results") or []):
        if _report_id_for_result(result if isinstance(result, dict) else None) == report_id:
            return True
    for role in TEAM_LEAD_ALLOWED_ROLES:
        result = state.get(f"{role}_result")
        if _report_id_for_result(result if isinstance(result, dict) else None) == report_id:
            return True
    return False


def _validate_accepted_report_ids(state: OpenHandsGraphState, decision: TeamLeadDecision) -> tuple[bool, str | None]:
    for role, report_id in _accepted_report_ids(decision).items():
        if not report_id:
            continue
        if str(role) not in TEAM_LEAD_ALLOWED_ROLES:
            return False, f"accepted_report_ids contains unsupported role: {role}"
        if not _report_id_exists(state, str(report_id)):
            return False, f"accepted_report_ids.{role} references unknown report_id: {report_id}"
    return True, None


def _scout_requires_research(state: OpenHandsGraphState) -> bool:
    scout = _latest_result_for_role(state, "scout") or {}
    summary = _summary_dict(scout)
    report = scout.get("role_report") if isinstance(scout, dict) else None
    facts = report.get("facts") if isinstance(report, dict) and isinstance(report.get("facts"), dict) else {}
    values = [summary, report if isinstance(report, dict) else {}, facts]
    for value in values:
        if not isinstance(value, dict):
            continue
        if _truthy(value.get("research_required")):
            return True
        if value.get("research_domains") or value.get("research_questions"):
            return True
    return False


def _research_waiver_ok(state: OpenHandsGraphState, decision: TeamLeadDecision) -> tuple[bool, str | None]:
    if _latest_pass_result_for_role(state, "research"):
        return True, None
    if not _scout_requires_research(state):
        return True, None
    policy = _decision_policy(decision)
    if _truthy(policy.get("can_skip_research")) and _non_empty_string(policy.get("skip_research_reason")):
        accepted = _accepted_report_ids(decision)
        if accepted.get("scout"):
            return True, None
        return False, "research waiver requires accepted_report_ids.scout"
    return False, "Scout requested research; Team Lead must run Research or provide explicit research waiver"


def _architect_waiver_ok(state: OpenHandsGraphState, decision: TeamLeadDecision) -> tuple[bool, str | None]:
    if _latest_pass_result_for_role(state, "architect"):
        return True, None
    policy = _decision_policy(decision)
    if not (_truthy(policy.get("can_skip_architect")) and _non_empty_string(policy.get("skip_architect_reason"))):
        return False, "Architect has not passed; Team Lead must run Architect or provide explicit architect waiver"
    accepted = _accepted_report_ids(decision)
    if not accepted.get("senior_staff_engineer") and _latest_pass_result_for_role(state, "senior_staff_engineer"):
        return False, "architect waiver requires accepted_report_ids.senior_staff_engineer"
    if not accepted.get("scout") and _latest_pass_result_for_role(state, "scout"):
        return False, "architect waiver requires accepted_report_ids.scout"
    return True, None


def _qa_pass_after_latest_coder(state: OpenHandsGraphState) -> JsonDict | None:
    coder_idx = _latest_coder_pass_index(state)
    return _latest_pass_result_for_role_after_index(state, "qa", coder_idx)


def _qa_skip_ok(state: OpenHandsGraphState, decision: TeamLeadDecision) -> tuple[bool, str | None]:
    qa_result = _qa_pass_after_latest_coder(state)
    if qa_result:
        return True, None
    coder_result = _latest_coder_pass_result(state)
    if not coder_result:
        return False, "Cannot skip QA before a usable Coder PASS"
    policy = _decision_policy(decision)
    if not (_truthy(policy.get("can_skip_qa")) and _non_empty_string(policy.get("skip_qa_reason"))):
        return False, "QA has not passed; skipping QA requires can_skip_qa=true and skip_qa_reason"
    accepted = _accepted_report_ids(decision)
    if not accepted.get("coder"):
        return False, "QA waiver requires accepted_report_ids.coder"
    risks = policy.get("accepted_risks")
    if not (isinstance(risks, list) and risks):
        return False, "QA waiver must list residual risk in policy_evaluation.accepted_risks"
    return True, None


def _reviewer_pass_after_validation_gate(state: OpenHandsGraphState) -> JsonDict | None:
    coder_idx = _latest_coder_pass_index(state)
    qa_idx, qa_result = _latest_result_index_for_role(state, "qa")
    after_idx = qa_idx if qa_result and _role_action_pass(qa_result) else coder_idx
    return _latest_pass_result_for_role_after_index(state, "reviewer", after_idx)


def _reviewer_skip_ok(state: OpenHandsGraphState, decision: TeamLeadDecision) -> tuple[bool, str | None]:
    reviewer = _reviewer_pass_after_validation_gate(state)
    if reviewer:
        return True, None
    policy = _decision_policy(decision)
    if not (_truthy(policy.get("can_skip_reviewer")) and _non_empty_string(policy.get("skip_reviewer_reason"))):
        return False, "Reviewer has not passed; skipping Reviewer requires can_skip_reviewer=true and skip_reviewer_reason"
    accepted = _accepted_report_ids(decision)
    if not (accepted.get("coder") or accepted.get("qa")):
        return False, "Reviewer waiver requires accepted coder or QA report id"
    risks = policy.get("accepted_risks")
    if not (isinstance(risks, list) and risks):
        return False, "Reviewer waiver must list residual risk in policy_evaluation.accepted_risks"
    return True, None


def _publisher_pr_checks(result: JsonDict | None) -> JsonDict:
    if not isinstance(result, dict):
        return {}
    summary = _summary_dict(result)
    for candidate in (
        summary.get("pr_checks"),
        (result.get("role_report") or {}).get("pr_checks") if isinstance(result.get("role_report"), dict) else None,
        _extract_answer_object(result, "pr_checks"),
    ):
        if isinstance(candidate, dict):
            return candidate
    return {}


def _publisher_publish(result: JsonDict | None) -> JsonDict:
    if not isinstance(result, dict):
        return {}
    summary = _summary_dict(result)
    for candidate in (
        summary.get("publish"),
        (result.get("role_report") or {}).get("publish") if isinstance(result.get("role_report"), dict) else None,
        _extract_answer_object(result, "publish"),
    ):
        if isinstance(candidate, dict):
            return candidate
    return {}


def _publisher_pr_checks_ok(result: JsonDict | None) -> tuple[bool, str | None, bool]:
    if not _role_action_pass(result):
        return False, "Publisher did not return a usable PASS result", False
    checks = _publisher_pr_checks(result)
    publish = _publisher_publish(result)
    head_sha = checks.get("head_sha") or publish.get("head_sha") or publish.get("commit")
    pr_url = publish.get("pr_url") or publish.get("url") or publish.get("html_url")
    if not head_sha:
        return False, "Publisher PASS lacks head_sha/commit evidence", False
    if not pr_url and not publish.get("pr_number"):
        return False, "Publisher PASS lacks PR URL/number evidence", False
    if not _truthy(checks.get("waited")):
        return False, "Publisher did not wait/inspect checks", False

    failing = checks.get("failing_checks") or checks.get("failed_checks") or []
    pending = checks.get("pending_checks") or []
    if failing:
        return False, "Publisher reported failing checks", False
    if pending:
        return False, "Publisher reported pending checks", False

    overall = str(checks.get("overall_status") or checks.get("status") or checks.get("state") or "").strip().lower()
    check_runs = checks.get("check_runs") if isinstance(checks.get("check_runs"), list) else []
    commit_status = checks.get("commit_status") if isinstance(checks.get("commit_status"), dict) else {}
    status_state = str(commit_status.get("state") or "").strip().lower()

    if overall in {"passed", "pass", "success", "successful", "ok"}:
        if check_runs or status_state in {"success", "passed", "ok"}:
            return True, None, False
        return False, "Publisher says checks passed but no check-run/status evidence was included", False

    no_checks_statuses = {"no_checks_configured", "no_checks_found", "no_checks", "no_checks_available", "none"}
    if overall in no_checks_statuses or _truthy(checks.get("no_checks_configured")) or checks.get("checks_expected") is False:
        return True, None, True

    return False, f"Publisher check status is not acceptable: {overall or 'missing'}", False


def _last_specialist_result(state: OpenHandsGraphState) -> JsonDict | None:
    for result in reversed(list(state.get("role_results") or [])):
        if isinstance(result, dict) and str(result.get("role") or "").lower() != "team_lead":
            return result
    return None


def _retry_same_role_required(state: OpenHandsGraphState, decision: TeamLeadDecision) -> tuple[bool, str | None]:
    last = _last_specialist_result(state)
    if not isinstance(last, dict):
        return True, None
    if last.get("ok") is True or _summary_action(last) not in {"FAILED"} | BLOCK_ACTIONS:
        return True, None
    if not _truthy(last.get("retryable")):
        return True, None
    last_role = str(last.get("role") or "").lower()
    last_instance = str(last.get("role_instance") or "") or None
    if decision.action != "RETRY_ROLE":
        return False, f"Last specialist role {last_role} failed before usable output; retry same role or stop/ask human"
    if decision.next_role != last_role:
        return False, f"Retry must target the failed role {last_role}, not {decision.next_role}"
    if last_instance and decision.role_instance and decision.role_instance != last_instance:
        return False, f"Retry must reuse failed role_instance {last_instance}"
    return True, None


def _validate_team_lead_decision(state: OpenHandsGraphState, decision: TeamLeadDecision) -> tuple[bool, str | None]:
    action = normalize_action(decision.action)
    if action not in TEAM_LEAD_RUN_ACTIONS and action not in TEAM_LEAD_STOP_ACTIONS:
        return False, f"unsupported Team Lead action: {action}"

    ids_ok, ids_error = _validate_accepted_report_ids(state, decision)
    if not ids_ok:
        return False, ids_error

    if action == "STOP_COMPLETED":
        policy = _decision_policy(decision)
        if not _truthy(policy.get("can_complete")):
            return False, "STOP_COMPLETED requires policy_evaluation.can_complete=true"
        if not _truthy(policy.get("publisher_pr_checks_accepted")):
            return False, "STOP_COMPLETED requires publisher_pr_checks_accepted=true"
        publisher = _latest_pass_result_for_role(state, "publisher")
        checks_ok, checks_reason, no_checks = _publisher_pr_checks_ok(publisher)
        if not checks_ok:
            return False, checks_reason
        if no_checks and not _truthy(policy.get("publisher_no_checks_accepted")):
            return False, "No-checks Publisher PASS requires publisher_no_checks_accepted=true"
        return True, None

    if action in {"STOP_BLOCKED", "ASK_HUMAN"}:
        return True, None

    if not decision.next_role or decision.next_role not in TEAM_LEAD_ALLOWED_ROLES:
        return False, "RUN_ROLE/RETRY_ROLE requires supported next_role"

    retry_ok, retry_error = _retry_same_role_required(state, decision)
    if not retry_ok:
        return False, retry_error

    next_role = decision.next_role
    if next_role == "scout":
        return _enforce_scout_facts_only_decision(decision)

    if next_role in {"senior_staff_engineer", "architect", "coder", "qa", "reviewer", "publisher"}:
        research_ok, research_error = _research_waiver_ok(state, decision)
        if not research_ok:
            return False, research_error

    if next_role == "coder":
        return _architect_waiver_ok(state, decision)

    if next_role == "qa":
        if not _latest_coder_pass_result(state):
            return False, "QA cannot run before a usable Coder PASS"
        return True, None

    if next_role == "reviewer":
        if not _latest_coder_pass_result(state):
            return False, "Reviewer cannot run before a usable Coder PASS"
        return _qa_skip_ok(state, decision)

    if next_role == "publisher":
        if not _latest_coder_pass_result(state):
            return False, "Publisher cannot run before a usable Coder PASS"
        qa_ok, qa_error = _qa_skip_ok(state, decision)
        if not qa_ok:
            return False, qa_error
        reviewer_ok, reviewer_error = _reviewer_skip_ok(state, decision)
        if not reviewer_ok:
            return False, reviewer_error
        if not _truthy(_decision_policy(decision).get("can_publish")):
            return False, "Publisher requires policy_evaluation.can_publish=true"
        return True, None

    return True, None


def _enforce_scout_facts_only_decision(decision: TeamLeadDecision) -> tuple[bool, str | None]:
    if decision.next_role != "scout":
        return True, None
    text = f"{decision.instructions or ''}\n{decision.reason or ''}".lower()
    forbidden = [
        "root cause",
        "root-cause",
        "hypothesis",
        "hypothesize",
        "solution",
        "fix plan",
        "implement",
        "patch",
        "run tests",
        "build",
    ]
    if any(marker in text for marker in forbidden):
        return False, SCOUT_FACTS_ONLY_INSTRUCTIONS
    if "fact" not in text and "context" not in text:
        return False, SCOUT_FACTS_ONLY_INSTRUCTIONS
    return True, None


async def _build_team_lead_runner(state: OpenHandsGraphState, config: Optional[RunnableConfig]) -> DirectLLMTeamLeadRunner:
    cfg = _configurable(config)
    runner = cfg.get("team_lead_runner")
    if isinstance(runner, DirectLLMTeamLeadRunner):
        return runner
    base_url = cfg.get("team_lead_base_url") or cfg.get("llm_base_url") or state.get("team_lead_base_url")
    model = cfg.get("team_lead_model") or state.get("team_lead_model") or state.get("model")
    api_key = cfg.get("team_lead_api_key") or cfg.get("llm_api_key") or state.get("team_lead_api_key")
    timeout = float(cfg.get("team_lead_timeout", 120.0))
    max_attempts = int(cfg.get("team_lead_max_attempts", 3))
    temperature = float(cfg.get("team_lead_temperature", 0.0))
    if not base_url or not model:
        raise OpenHandsLangGraphError("Team Lead requires team_lead_base_url/llm_base_url and team_lead_model/model")
    return DirectLLMTeamLeadRunner(
        base_url=str(base_url),
        model=str(model),
        api_key=str(api_key) if api_key else None,
        timeout=timeout,
        max_attempts=max_attempts,
        temperature=temperature,
    )


def _team_lead_result_from_decision(result: TeamLeadDecisionResult) -> JsonDict:
    decision = result.decision.normalized()
    decision_dict = decision.model_dump(mode="json")
    return {
        "role": "team_lead",
        "role_instance": "team_lead",
        "conversation_id": "direct-llm",
        "status": decision_dict.get("status", "completed"),
        "ok": True,
        "summary_status": decision_dict.get("status", "completed"),
        "summary_action": decision_dict.get("action"),
        "risk_level": decision_dict.get("risk_level"),
        "blocking": decision_dict.get("blocking", False),
        "summary": decision_dict,
        "answer": result.raw_response,
        "model": result.model,
        "usage": result.usage,
        "summary_attempt_count": result.attempts,
        "report_id": f"team_lead:{int(time.time())}",
    }


async def team_lead_node(
    state: OpenHandsGraphState,
    config: Optional[RunnableConfig] = None,
) -> OpenHandsGraphState:
    steps = int(state.get("team_lead_steps") or 0)
    max_steps = int(state.get("max_team_lead_steps") or 12)
    if steps >= max_steps:
        return {
            "team_lead_decision": {
                "action": "ASK_HUMAN",
                "summary": f"Team Lead reached max_team_lead_steps={max_steps}.",
                "blocking": True,
                "blocking_summary": ["max_team_lead_steps reached"],
            },
            "team_lead_steps": steps,
            "final_status": "needs_human_review",
            "final_answer": f"Team Lead reached max_team_lead_steps={max_steps} before a safe completion decision.",
        }

    ui = _workflow_ui(config)
    prompt = build_team_lead_decision_prompt(state)
    started_at = _utc_now_iso()
    started_monotonic = time.monotonic()
    try:
        runner = await _build_team_lead_runner(state, config)
        result = await runner.decide(prompt=prompt)
        result_dict = _team_lead_result_from_decision(result)
        decision = result.decision.normalized()
        valid, reason = _validate_team_lead_decision(state, decision)
        if not valid:
            retry_result = await runner.decide(
                prompt=prompt,
                validation_error=reason or "Team Lead decision failed structural policy validation",
            )
            result_dict = _team_lead_result_from_decision(retry_result)
            decision = retry_result.decision.normalized()
            valid, reason = _validate_team_lead_decision(state, decision)
        if not valid:
            decision_dict = decision.model_dump(mode="json")
            decision_dict.update(
                {
                    "action": "ASK_HUMAN",
                    "next_role": None,
                    "role_instance": None,
                    "blocking": True,
                    "blocking_summary": [reason or "Team Lead decision failed structural policy validation"],
                    "summary": "Team Lead decision failed structural policy validation.",
                }
            )
            result_dict["summary"] = decision_dict
            result_dict["summary_action"] = "ASK_HUMAN"
            result_dict["blocking"] = True
            decision = TeamLeadDecision.model_validate(decision_dict)
    except Exception as exc:
        duration = _round_seconds(time.monotonic() - started_monotonic)
        failed_result = _synthetic_failed_role_result(
            state,
            role="team_lead",
            role_instance="team_lead",
            error=exc,
            started_at=started_at,
            duration_seconds=duration,
        )
        role_results = list(state.get("role_results") or [])
        role_results.append(failed_result)
        errors = list(state.get("errors") or [])
        errors.append(f"team_lead: {exc}")
        return {
            "role_results": role_results,
            "team_lead_result": failed_result,
            "last_role_result": failed_result,
            "last_role_metrics": failed_result["metrics"],
            "team_lead_steps": steps + 1,
            "team_lead_decision": {
                "action": "ASK_HUMAN",
                "summary": "Team Lead direct LLM decision failed.",
                "blocking": True,
                "blocking_summary": [str(exc)],
            },
            "errors": errors,
            "final_status": "needs_human_review",
            "final_answer": f"Team Lead direct LLM decision failed: {exc}",
        }

    duration = _round_seconds(time.monotonic() - started_monotonic)
    result_dict["metrics"] = {
        "role": "team_lead",
        "role_instance": "team_lead",
        "started_at": started_at,
        "finished_at": _utc_now_iso(),
        "duration_seconds": duration,
        "summary_attempt_count": result_dict.get("summary_attempt_count", 1),
    }
    _trace_role_result("team_lead", result_dict, config)
    if ui is not None:
        try:
            ui.role_result("team_lead", result_dict)
        except Exception:
            pass

    role_results = list(state.get("role_results") or [])
    role_results.append(result_dict)
    decision_dict = result_dict.get("summary") if isinstance(result_dict.get("summary"), dict) else {}
    patch: OpenHandsGraphState = {
        "role_results": role_results,
        "team_lead_result": result_dict,
        "last_role_result": result_dict,
        "last_role_metrics": result_dict["metrics"],
        "team_lead_decision": decision_dict,
        "team_lead_steps": steps + 1,
        "final_status": "team_lead_decided",
        "final_answer": str(decision_dict.get("summary") or "Team Lead returned a routing decision."),
    }
    if decision.action == "STOP_COMPLETED":
        patch["final_status"] = "completed"
    elif decision.action == "STOP_BLOCKED":
        patch["final_status"] = "blocked"
    elif decision.action == "ASK_HUMAN":
        patch["final_status"] = "needs_human_review"
    return patch


async def dynamic_role_executor_node(
    state: OpenHandsGraphState,
    config: Optional[RunnableConfig] = None,
) -> OpenHandsGraphState:
    decision = state.get("team_lead_decision") or {}
    if not isinstance(decision, dict):
        return _append_error(state, "team_lead_decision is missing or invalid")
    role = str(decision.get("next_role") or "").strip().lower()
    if role not in TEAM_LEAD_ALLOWED_ROLES:
        return _append_error(state, f"unsupported Team Lead next_role: {role}")
    role_instance = str(decision.get("role_instance") or f"{role}-1")
    prompt = build_role_prompt(role, state)
    return await _run_role_with_prompt(
        state,
        config,
        role=role,
        role_instance=role_instance,
        prompt=prompt,
        summary_instructions=build_role_summary_instructions(role),
        persistent_session=True,
    )


def route_after_team_lead(state: OpenHandsGraphState) -> str:
    decision = state.get("team_lead_decision") or {}
    if not isinstance(decision, dict):
        return "end"
    action = normalize_action(decision.get("action"))
    if action in TEAM_LEAD_RUN_ACTIONS:
        return "role_executor"
    return "end"


# ---------------------------------------------------------------------------
# Route functions used by graph.py
# ---------------------------------------------------------------------------


def route_after_senior_staff(state: OpenHandsGraphState) -> str:
    return str(state.get("next_node") or "end")


def route_after_qa(state: OpenHandsGraphState) -> str:
    return str(state.get("next_node") or "end")


def route_after_review(state: OpenHandsGraphState) -> str:
    return str(state.get("next_node") or "end")


def route_continue_or_end(next_node: str):
    def _route(state: OpenHandsGraphState) -> str:
        if state.get("errors"):
            return "end"
        result = state.get("last_role_result") or {}
        action = _summary_action(result if isinstance(result, dict) else None)
        if action in PASS_ACTIONS or action == "":
            return next_node
        if action in NEED_FIX_ACTIONS or action in BLOCK_ACTIONS:
            return "end"
        if isinstance(result, dict) and result.get("blocking") is True:
            return "end"
        return next_node

    return _route
