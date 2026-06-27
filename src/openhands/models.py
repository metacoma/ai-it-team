from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

JsonDict = dict[str, Any]


class OpenHandsModel(BaseModel):
    """Base model for public SDK contracts.

    Raw OpenHands websocket/REST payloads remain tolerant dictionaries, but
    objects that cross the SDK/LangGraph boundary are validated and safely
    serializable through Pydantic.
    """

    model_config = ConfigDict(
        extra="allow",
        arbitrary_types_allowed=True,
        validate_assignment=False,
        populate_by_name=True,
    )

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class RoleSummary(OpenHandsModel):
    """Validated JSON summary returned by the LLM for one role run."""

    valid: bool = True
    status: str = "unknown"
    summary: str
    action: str | None = None
    risk_level: str | None = None
    blocking: bool = False
    blocking_summary: list[str] = Field(default_factory=list)


class SummaryAttempt(OpenHandsModel):
    attempt: int
    text: str
    parsed_json: RoleSummary | JsonDict | list[Any] | None = None
    error: str | None = None
    conversation_id: str | None = None

    @computed_field
    @property
    def valid(self) -> bool:
        return self.error is None and self.parsed_json is not None

    def to_dict(self, *, include_text: bool = True) -> JsonDict:
        exclude: set[str] = set()
        if not include_text:
            exclude.add("text")
        return self.model_dump(mode="json", exclude=exclude)


class AppConversationStart(OpenHandsModel):
    conversation_id: str
    task_id: str | None = None
    status: str | None = None
    sandbox_id: str | None = None
    agent_server_url: str | None = None
    conversation_url: str | None = None
    session_api_key: str | None = Field(default=None, exclude=True, repr=False)
    raw_task: JsonDict | None = Field(default=None, repr=False)
    raw_conversation: JsonDict | None = Field(default=None, repr=False)

    @computed_field
    @property
    def has_session_api_key(self) -> bool:
        return bool(self.session_api_key)

    def to_dict(self, *, include_raw: bool = False) -> JsonDict:
        exclude: set[str] = {"session_api_key"}
        if not include_raw:
            exclude.update({"raw_task", "raw_conversation"})
        return self.model_dump(mode="json", exclude=exclude)


class OpenHandsRunResult(OpenHandsModel):
    """Result of one completed OpenHands conversation run."""

    text: str
    status: str | None = None
    conversation_id: str
    start: AppConversationStart
    seen_event_ids: frozenset[str] = Field(default_factory=frozenset)

    @computed_field
    @property
    def has_answer(self) -> bool:
        return bool(self.text.strip())

    @computed_field
    @property
    def seen_event_count(self) -> int:
        return len(self.seen_event_ids)

    def to_dict(self, *, include_text: bool = True, include_start: bool = True) -> JsonDict:
        exclude: set[str] = {"seen_event_ids"}
        if not include_text:
            exclude.add("text")
        if not include_start:
            exclude.add("start")
        return self.model_dump(mode="json", exclude=exclude)


class RoleRunSpec(OpenHandsModel):
    role: str
    prompt: str
    role_instance: str | None = None
    model: str | None = None
    repository: str | None = None
    branch: str | None = None
    git_provider: str | None = None
    sandbox_id: str | None = None
    conversation_id: str | None = None
    title: str | None = None
    extra_payload: JsonDict | None = None
    conversation_params: JsonDict = Field(default_factory=dict)


class RoleRunResult(OpenHandsModel):
    answer: str
    summary_text: str
    summary_json: RoleSummary
    answer_run: OpenHandsRunResult
    summary_attempts: list[SummaryAttempt] = Field(default_factory=list)
    role: str = "role"
    role_instance: str | None = None
    # Runtime helper object; intentionally excluded from LangGraph/JSON state.
    conversation: Any | None = Field(default=None, exclude=True, repr=False)
    error: str | None = None
    # Event ids seen through the latest role+summary run. Kept out of public JSON
    # by default, but LangGraph SessionManager uses it to ignore replayed events
    # when reusing persistent role conversations.
    seen_event_ids: frozenset[str] = Field(default_factory=frozenset, exclude=True, repr=False)

    @computed_field
    @property
    def conversation_id(self) -> str:
        return self.answer_run.conversation_id

    @computed_field
    @property
    def status(self) -> str | None:
        return self.answer_run.status

    @computed_field
    @property
    def raw_summary(self) -> str:
        return self.summary_text

    @computed_field
    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.answer.strip()) and self.summary_json.valid

    @computed_field
    @property
    def summary_status(self) -> str | None:
        return self.summary_json.status

    @computed_field
    @property
    def summary_action(self) -> str | None:
        return self.summary_json.action

    @computed_field
    @property
    def risk_level(self) -> str | None:
        return self.summary_json.risk_level

    @computed_field
    @property
    def blocking(self) -> bool:
        return self.summary_json.blocking

    def to_dict(
        self,
        *,
        include_answer: bool = True,
        include_raw_summary: bool = True,
        include_attempt_text: bool = False,
    ) -> JsonDict:
        data: JsonDict = {
            "role": self.role,
            "role_instance": self.role_instance,
            "conversation_id": self.conversation_id,
            "status": self.status,
            "ok": self.ok,
            "summary_status": self.summary_status,
            "summary_action": self.summary_action,
            "risk_level": self.risk_level,
            "blocking": self.blocking,
            "summary": self.summary_json.model_dump(mode="json"),
            "summary_attempt_count": len(self.summary_attempts),
            "summary_attempts": [
                attempt.to_dict(include_text=include_attempt_text) for attempt in self.summary_attempts
            ],
            "error": self.error,
            "answer_run": self.answer_run.to_dict(include_text=False, include_start=True),
            "seen_event_count": len(self.seen_event_ids),
        }
        if include_answer:
            data["answer"] = self.answer
        if include_raw_summary:
            data["raw_summary"] = self.raw_summary
        return data
