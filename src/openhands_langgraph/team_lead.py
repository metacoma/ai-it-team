from __future__ import annotations

import json
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

JsonDict = dict[str, Any]

_ALLOWED_ACTIONS = {
    "RUN_ROLE",
    "RETRY_ROLE",
    "STOP_COMPLETED",
    "STOP_BLOCKED",
    "ASK_HUMAN",
}
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


def _coerce_string_list(value: Any) -> list[str]:
    """Accept common LLM list mistakes while keeping the public contract typed.

    Local models often return comma-separated strings for fields that are
    explicitly documented as arrays. Treat those as recoverable formatting
    issues so the Team Lead can be normalized and structurally validated instead
    of failing before policy checks run.
    """

    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return _coerce_string_list(parsed)
        normalized = text.replace("\n", ",").replace(";", ",")
        return [item.strip().strip("\"'") for item in normalized.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            if isinstance(item, str) and ("," in item or "\n" in item or ";" in item):
                items.extend(_coerce_string_list(item))
            elif item is not None:
                items.append(str(item).strip())
        return [item for item in items if item]
    return [str(value).strip()] if str(value).strip() else []

class TeamLeadPolicyEvaluation(BaseModel):
    """Structured rationale for Team Lead routing decisions.

    The orchestration layer validates only structural safety: known actions/roles,
    known report ids, explicit waivers, and publish completion evidence. The Team
    Lead still owns the semantic decision: which roles are needed for this task,
    which validation gaps are acceptable, and which risks require another role.
    """

    model_config = ConfigDict(extra="allow")

    can_review: bool | None = None
    can_publish: bool | None = None
    can_complete: bool | None = None
    qa_evidence_accepted: bool | None = None
    reviewer_evidence_accepted: bool | None = None
    publisher_pr_checks_accepted: bool | None = None
    publisher_publication_evidence_accepted: bool | None = None
    external_publication_accepted: bool | None = None
    publication_target_verified: bool | None = None
    publication_content_reviewed: bool | None = None
    no_repo_changes_accepted: bool | None = None
    target_verified: bool | None = None
    content_prepared: bool | None = None
    can_skip_discovery: bool | None = None
    skip_discovery_reason: str | None = None
    validation_profile_accepted: bool | None = None
    pr_feedback_accepted: bool | None = None
    corrective_loop_required: bool | None = None

    # Explicit waiver fields keep LangGraph as a structural safety kernel while
    # allowing Team Lead to own subjective process decisions.
    can_skip_research: bool | None = None
    skip_research_reason: str | None = None
    can_skip_architect: bool | None = None
    skip_architect_reason: str | None = None
    can_skip_qa: bool | None = None
    skip_qa_reason: str | None = None
    can_skip_reviewer: bool | None = None
    skip_reviewer_reason: str | None = None

    # Publisher can report a structured no-checks case when the repository has no
    # CI/check configuration. Team Lead may accept that as completed PR evidence.
    publisher_no_checks_accepted: bool | None = None

    scout_research_needed_accepted: bool | None = None
    senior_staff_strategy_accepted: bool | None = None
    implementation_scope_accepted: bool | None = None
    blocking_reasons: list[str] = Field(default_factory=list)
    accepted_risks: list[str] = Field(default_factory=list)

    @field_validator("blocking_reasons", "accepted_risks", mode="before")
    @classmethod
    def _coerce_policy_lists(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)


class TeamLeadAcceptedReportIds(BaseModel):
    model_config = ConfigDict(extra="allow")

    scout: str | None = None
    research: str | None = None
    senior_staff_engineer: str | None = None
    architect: str | None = None
    coder: str | None = None
    qa: str | None = None
    reviewer: str | None = None
    publisher: str | None = None


class TeamLeadAssignmentScopeCheck(BaseModel):
    """Self-check that current-role instructions match the selected role capability.

    This is intentionally declarative: LangGraph still validates the resulting
    decision structurally and rejects unsafe cross-role assignments instead of
    silently rewriting them.
    """

    model_config = ConfigDict(extra="allow")

    selected_role: str | None = None
    instructions_contain_only_selected_role_work: bool | None = None
    future_work_not_instructions: bool | None = None
    publishing_actions_in_non_publisher_assignment: bool | None = None
    notes: str | None = None


class TeamLeadWorkOrder(BaseModel):
    """Task classification used by the policy-driven Team Lead router.

    Work orders decouple the workflow from a fixed development chain. Existing
    specialist roles are selected by capability and required evidence instead
    of by ceremony. Unknown/extra fields are allowed so future roles and policy
    surfaces can be introduced without breaking older clients.
    """

    model_config = ConfigDict(extra="allow")

    intent: str | None = None
    target_system: str | None = None
    change_surface: Literal[
        "none",
        "repository",
        "external_publication",
        "live_server",
        "kubernetes_cluster",
        "monitoring",
        "database",
        "network",
        "security",
        "unknown",
    ] = "repository"
    artifact_kind: str | None = None
    execution_strategy: Literal[
        "answer_only",
        "repo_change",
        "direct_external_api",
        "direct_live_execution",
        "iac_or_gitops",
        "investigation_only",
        "unknown",
    ] = "repo_change"
    risk_level: Literal["low", "medium", "high", "critical"] | None = None
    requires_human_approval: bool | None = None
    requires_rollback_plan: bool | None = None
    requires_validation: bool | None = None
    required_evidence: list[str] = Field(default_factory=list)
    completed_evidence: list[str] = Field(default_factory=list)
    forbidden_roles: list[str] = Field(default_factory=list)
    preferred_roles: list[str] = Field(default_factory=list)

    @field_validator(
        "required_evidence",
        "completed_evidence",
        "forbidden_roles",
        "preferred_roles",
        mode="before",
    )
    @classmethod
    def _coerce_work_order_lists(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)


class TeamLeadDecision(BaseModel):
    """Tool-less Team Lead routing decision."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    valid: bool = True
    status: str = "completed"
    summary: str
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
    work_order: TeamLeadWorkOrder = Field(default_factory=TeamLeadWorkOrder)
    capabilities_required: list[str] = Field(default_factory=list)
    context_sources: list[str] = Field(default_factory=list)
    instructions: str = ""
    future_workflow_plan: list[str] = Field(default_factory=list)
    assignment_scope_check: TeamLeadAssignmentScopeCheck = Field(default_factory=TeamLeadAssignmentScopeCheck)
    reason: str = ""
    accepted_report_ids: TeamLeadAcceptedReportIds = Field(default_factory=TeamLeadAcceptedReportIds)
    policy_evaluation: TeamLeadPolicyEvaluation = Field(default_factory=TeamLeadPolicyEvaluation)

    @field_validator(
        "blocking_summary",
        "capabilities_required",
        "context_sources",
        "future_workflow_plan",
        mode="before",
    )
    @classmethod
    def _coerce_decision_lists(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)

    def normalized(self) -> "TeamLeadDecision":
        data = self.model_dump(mode="python")
        data["action"] = str(data.get("action") or "").strip().upper().replace("-", "_").replace(" ", "_")
        if data["action"] not in _ALLOWED_ACTIONS:
            raise ValueError(f"unsupported Team Lead action: {data['action']}")

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

        return TeamLeadDecision.model_validate(data)


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
                    "Return exactly one compact valid JSON object matching the requested schema."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        if validation_error:
            messages.append(
                {
                    "role": "user",
                    "content": "Previous decision was invalid: "
                    + validation_error
                    + "\nReturn a corrected JSON decision only.",
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
                            "Return only one valid JSON object. Do not include Markdown or prose."
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
            except Exception as exc:
                last_error = exc
                messages.append({"role": "assistant", "content": last_text or f"ERROR: {exc}"})
                continue

        raise RuntimeError(
            f"Team Lead LLM did not return a valid decision after {self.max_attempts} attempts: {last_error}"
        )


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
