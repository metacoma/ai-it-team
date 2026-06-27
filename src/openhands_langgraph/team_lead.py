from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

JsonDict = dict[str, Any]

_ALLOWED_ACTIONS = {"RUN_ROLE", "RETRY_ROLE", "STOP_COMPLETED", "STOP_BLOCKED", "ASK_HUMAN"}
_ALLOWED_ROLES = {
    "scout",
    "research",
    "senior_staff_engineer",
    "architect",
    "coder",
    "qa",
    "reviewer",
    "publisher",
}
_ACTION_ALIASES = {
    "PASS": "STOP_COMPLETED",
    "COMPLETED": "STOP_COMPLETED",
    "COMPLETE": "STOP_COMPLETED",
    "DONE": "STOP_COMPLETED",
    "BLOCK": "STOP_BLOCKED",
    "BLOCKED": "STOP_BLOCKED",
    "STOP": "STOP_BLOCKED",
    "RUN": "RUN_ROLE",
    "RUN": "RUN_ROLE",
    "RETRY": "RETRY_ROLE",
    "HUMAN": "ASK_HUMAN",
    "ASK_USER": "ASK_HUMAN",
}
_NULL_REPORT_ID_VALUES = {"", "none", "null", "nil", "n/a", "na", "unknown"}
_HEX_CHARS = set("0123456789abcdefABCDEF")
_SERVER_REPORT_ID_PREFIXES = ("report:", "role-report:", "role_report:")


class TeamLeadPolicyEvaluation(BaseModel):
    model_config = ConfigDict(extra="allow")

    can_review: bool | None = None
    can_publish: bool | None = None
    can_complete: bool | None = None
    qa_evidence_accepted: bool | None = None
    reviewer_evidence_accepted: bool | None = None
    publisher_pr_checks_accepted: bool | None = None
    validation_profile_accepted: bool | None = None
    pr_feedback_accepted: bool | None = None
    corrective_loop_required: bool | None = None
    can_skip_research: bool | None = None
    skip_research_reason: str | None = None
    can_skip_architect: bool | None = None
    skip_architect_reason: str | None = None
    scout_research_needed_accepted: bool | None = None
    senior_staff_strategy_accepted: bool | None = None
    implementation_scope_accepted: bool | None = None
    blocking_reasons: list[str] = Field(default_factory=list)
    accepted_risks: list[str] = Field(default_factory=list)


class TeamLeadAcceptedReportIds(BaseModel):
    """Advisory accepted report ids returned by the LLM.

    The authoritative set must be resolved from graph state by Python code.
    This object is kept for backward compatibility, but normalization strips
    role-run/conversation shaped values and any non-server ids so the LLM cannot
    invent state references.
    """

    model_config = ConfigDict(extra="forbid")

    scout: str | None = None
    research: str | None = None
    senior_staff_engineer: str | None = None
    architect: str | None = None
    coder: str | None = None
    qa: str | None = None
    reviewer: str | None = None
    publisher: str | None = None


class TeamLeadResolvedReportIds(BaseModel):
    """Authoritative report ids resolved by deterministic Python reducers."""

    model_config = ConfigDict(extra="forbid")

    scout: str | None = None
    research: str | None = None
    senior_staff_engineer: str | None = None
    architect: str | None = None
    coder: str | None = None
    qa: str | None = None
    reviewer: str | None = None
    publisher: str | None = None


class TeamLeadDecisionRaw(BaseModel):
    """Minimal LLM-controlled decision surface.

    Prefer this contract for new Team Lead prompts: the model chooses intent
    only. Role report ids, conversation ids, role_run ids, input artifacts, and
    accepted_report_ids must be filled server-side after validation.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    action: Literal["RUN_ROLE", "RETRY_ROLE", "STOP_COMPLETED", "STOP_BLOCKED", "ASK_HUMAN"]
    next_role: Literal[
        "scout",
        "research",
        "senior_staff_engineer",
        "architect",
        "coder",
        "qa",
        "reviewer",
        "publisher",
    ] | None = None
    reason: str = ""
    risk_level: Literal["low", "medium", "high", "critical"] | None = None
    blocking: bool = False
    blocking_summary: list[str] = Field(default_factory=list)


class TeamLeadDecisionResolved(BaseModel):
    """Server-side decision after state-derived facts have been attached."""

    model_config = ConfigDict(extra="forbid")

    raw: TeamLeadDecisionRaw
    role_instance: str | None = None
    accepted_report_ids: TeamLeadResolvedReportIds = Field(default_factory=TeamLeadResolvedReportIds)
    input_report_ids: TeamLeadResolvedReportIds = Field(default_factory=TeamLeadResolvedReportIds)


class TeamLeadDecision(BaseModel):
    """Backward-compatible Team Lead routing decision.

    Existing graph code still consumes this shape. It deliberately normalizes
    away LLM-controlled state ids so the Team Lead can decide *what* to do next
    but cannot invent *which* internal reports were accepted.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    valid: bool = True
    status: str = "completed"
    summary: str = ""
    action: Literal["RUN_ROLE", "RETRY_ROLE", "STOP_COMPLETED", "STOP_BLOCKED", "ASK_HUMAN"]
    risk_level: Literal["low", "medium", "high", "critical"] | None = None
    blocking: bool = False
    blocking_summary: list[str] = Field(default_factory=list)
    next_role: Literal[
        "scout",
        "research",
        "senior_staff_engineer",
        "architect",
        "coder",
        "qa",
        "reviewer",
        "publisher",
    ] | None = None
    role_instance: str | None = None
    context_sources: list[str] = Field(default_factory=list)
    instructions: str = ""
    reason: str = ""
    accepted_report_ids: TeamLeadAcceptedReportIds = Field(default_factory=TeamLeadAcceptedReportIds)
    policy_evaluation: TeamLeadPolicyEvaluation = Field(default_factory=TeamLeadPolicyEvaluation)

    @model_validator(mode="before")
    @classmethod
    def _accept_common_aliases(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data
        patched = dict(data)
        if patched.get("action") is not None:
            patched["action"] = _normalize_action_name(patched.get("action"))
        if patched.get("risk_level") is None and patched.get("risk") is not None:
            patched["risk_level"] = patched.get("risk")
        if not patched.get("summary") and patched.get("reason"):
            patched["summary"] = str(patched.get("reason"))
        return patched

    def normalized(self) -> "TeamLeadDecision":
        data = self.model_dump(mode="python")
        data["action"] = _normalize_action_name(data.get("action"))
        role = data.get("next_role")
        if role:
            data["next_role"] = str(role).strip().lower()
            if data["next_role"] not in _ALLOWED_ROLES:
                raise ValueError(f"unsupported Team Lead role: {data['next_role']}")
        if data["action"] in {"RUN_ROLE", "RETRY_ROLE"}:
            if not data.get("next_role"):
                raise ValueError("RUN_ROLE/RETRY_ROLE requires next_role")
            if not data.get("role_instance"):
                data["role_instance"] = f"{data['next_role']}-1"
        else:
            data["next_role"] = None
            data["role_instance"] = None
        data["accepted_report_ids"] = _sanitize_llm_accepted_report_ids(data.get("accepted_report_ids"))
        return TeamLeadDecision.model_validate(data)

    def raw_decision(self) -> TeamLeadDecisionRaw:
        normalized = self.normalized()
        return TeamLeadDecisionRaw(
            action=normalized.action,
            next_role=normalized.next_role,
            reason=normalized.reason or normalized.summary,
            risk_level=normalized.risk_level,
            blocking=normalized.blocking,
            blocking_summary=list(normalized.blocking_summary or []),
        )


class TeamLeadDecisionResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    decision: TeamLeadDecision
    raw_response: str
    attempts: int = 1
    model: str | None = None
    usage: JsonDict | None = None


class DirectLLMTeamLeadRunner:
    """Direct OpenAI-compatible Team Lead decision runner.

    This deliberately bypasses OpenHands so the Team Lead has no shell, browser,
    task tracker, file access, or sandbox. It only sees serialized graph state
    and returns a JSON decision.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 120.0,
        max_attempts: int = 3,
        temperature: float = 0.0,
    ) -> None:
        if not base_url:
            raise ValueError("Team Lead LLM base_url is required")
        if not model:
            raise ValueError("Team Lead LLM model is required")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_attempts = max(1, int(max_attempts))
        self.temperature = temperature

    @property
    def chat_completions_url(self) -> str:
        base = self.base_url
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return base + "/chat/completions"
        return base + "/v1/chat/completions"

    async def decide(self, *, prompt: str, validation_error: str | None = None) -> TeamLeadDecisionResult:
        messages: list[JsonDict] = [
            {
                "role": "system",
                "content": (
                    "You are a tool-less Team Lead decision engine. You have no tools. "
                    "You cannot inspect files, run commands, browse, edit code, push, or create PRs. "
                    "Return exactly one compact valid JSON object matching the requested schema. "
                    "Do not invent or copy report ids, conversation ids, role_run ids, artifact paths, "
                    "branch names, or commit shas. Internal ids are resolved by the orchestrator."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        if validation_error:
            messages.append(
                {
                    "role": "user",
                    "content": "Previous decision was invalid: " + validation_error + "\nReturn a corrected JSON decision only.",
                }
            )
        last_text = ""
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            if attempt > 1:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous response was not valid JSON or did not match the schema. "
                            "Return only one valid JSON object. Do not include Markdown or prose. "
                            "Never produce accepted_report_ids; the orchestrator resolves those."
                        ),
                    }
                )
            try:
                payload: JsonDict = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "stream": False,
                }
                headers: dict[str, str] = {"Content-Type": "application/json"}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(self.chat_completions_url, headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                text = _extract_chat_completion_text(data)
                last_text = text
                parsed = _parse_json_object(text)
                decision = TeamLeadDecision.model_validate(parsed).normalized()
                return TeamLeadDecisionResult(
                    decision=decision,
                    raw_response=text,
                    attempts=attempt,
                    model=str(data.get("model") or self.model),
                    usage=data.get("usage") if isinstance(data.get("usage"), dict) else None,
                )
            except Exception as exc:  # retry invalid model output and transient HTTP failures uniformly here.
                last_error = exc
                messages.append({"role": "assistant", "content": last_text or f"ERROR: {exc}"})
                continue
        raise RuntimeError(f"Team Lead LLM did not return a valid decision after {self.max_attempts} attempts: {last_error}")


def resolve_team_lead_decision(
    decision: TeamLeadDecision,
    state: Mapping[str, Any],
    *,
    input_roles: list[str] | None = None,
) -> TeamLeadDecisionResolved:
    """Attach deterministic state-derived ids to a Team Lead decision.

    This is the safe path for new graph code: ignore LLM-provided
    ``accepted_report_ids`` and compute them from the append-only ``role_results``
    list instead.
    """

    normalized = decision.normalized()
    raw = normalized.raw_decision()
    resolved_ids = TeamLeadResolvedReportIds.model_validate(resolve_latest_report_ids(state))
    if input_roles is None:
        input_ids = resolved_ids
    else:
        all_ids = resolved_ids.model_dump(mode="python")
        input_ids = TeamLeadResolvedReportIds.model_validate({role: all_ids.get(role) for role in input_roles})
    return TeamLeadDecisionResolved(
        raw=raw,
        role_instance=normalized.role_instance,
        accepted_report_ids=resolved_ids,
        input_report_ids=input_ids,
    )


def resolve_latest_report_ids(state: Mapping[str, Any]) -> dict[str, str | None]:
    """Return latest usable report_id for each role from append-only state.

    The reducer scans ``role_results`` in order and only uses ids that are already
    present in state. It never trusts ids emitted by Team Lead JSON.
    """

    resolved: dict[str, str | None] = {role: None for role in sorted(_ALLOWED_ROLES)}
    role_results = state.get("role_results") if isinstance(state, Mapping) else None
    if not isinstance(role_results, list):
        role_results = []
    for result in role_results:
        if not isinstance(result, Mapping):
            continue
        role = str(result.get("role") or "").strip().lower()
        if role not in _ALLOWED_ROLES:
            continue
        report_id = _report_id_from_role_result(result)
        if report_id:
            resolved[role] = report_id
    return resolved


def _report_id_from_role_result(result: Mapping[str, Any]) -> str | None:
    for key in ("report_id", "role_report_id"):
        value = result.get(key)
        if value:
            return str(value)
    role_report = result.get("role_report")
    if isinstance(role_report, Mapping) and role_report.get("report_id"):
        return str(role_report.get("report_id"))
    summary = result.get("summary")
    if isinstance(summary, Mapping):
        embedded = summary.get("role_report")
        if isinstance(embedded, Mapping) and embedded.get("report_id"):
            return str(embedded.get("report_id"))
    return None


def _normalize_action_name(value: Any) -> str:
    action = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    action = _ACTION_ALIASES.get(action, action)
    if action not in _ALLOWED_ACTIONS:
        raise ValueError(f"unsupported Team Lead action: {action}")
    return action


def _sanitize_llm_accepted_report_ids(value: Any) -> TeamLeadAcceptedReportIds:
    if isinstance(value, TeamLeadAcceptedReportIds):
        raw_items = value.model_dump(mode="python")
    elif isinstance(value, Mapping):
        raw_items = dict(value)
    else:
        raw_items = {}
    sanitized = {
        role: _sanitize_llm_accepted_report_id(role, raw_items.get(role))
        for role in sorted(_ALLOWED_ROLES)
    }
    return TeamLeadAcceptedReportIds.model_validate(sanitized)


def _sanitize_llm_accepted_report_id(role: str, value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _NULL_REPORT_ID_VALUES:
        return None
    if _looks_like_conversation_id(text):
        return None
    if _looks_like_role_instance_conversation_id(role, text):
        return None
    # New canonical report ids should be server-prefixed. Keeping only explicit
    # server ids prevents the LLM from constructing plausible free-form ids from
    # visible role_instance/conversation data.
    if not text.startswith(_SERVER_REPORT_ID_PREFIXES):
        return None
    return text


def _looks_like_conversation_id(value: str) -> bool:
    compact = value.strip().replace("-", "")
    return len(compact) >= 16 and all(char in _HEX_CHARS for char in compact)


def _looks_like_role_instance_conversation_id(role: str, value: str) -> bool:
    if ":" not in value:
        return False
    left, right = value.split(":", 1)
    left = left.strip().lower()
    right = right.strip()
    return (left == role or left.startswith(f"{role}-")) and _looks_like_conversation_id(right)


def _extract_chat_completion_text(data: JsonDict) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("chat completion response has no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ValueError("chat completion choice has no message")
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    raise ValueError("chat completion message has no text content")


def _parse_json_object(text: str) -> JsonDict:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty Team Lead LLM response")
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < start:
            raise
        parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Team Lead response JSON is not an object")
    return parsed
