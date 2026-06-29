from __future__ import annotations

from typing import Any, TypedDict

JsonDict = dict[str, Any]


class OpenHandsGraphState(TypedDict, total=False):
    """Serializable state for OpenHands/LangGraph workflows.

    Runtime objects such as OpenHandsInstance/OpenHandsRoleRunner intentionally
    do not live here. Pass them through LangGraph's configurable runtime config.
    """

    # User-facing request
    user_task: str
    prompt: str
    role: str
    role_instance: str | None
    model: str | None

    # Per-role model overrides from YAML config.
    role_models: JsonDict | None

    repository: str | None
    branch: str | None
    git_provider: str | None
    sandbox_id: str | None
    conversation_id: str | None
    title: str | None
    extra_payload: JsonDict | None
    conversation_params: JsonDict
    workflow: str

    # Runtime controls for OpenHandsRoleRunner.run_role.
    role_run_options: JsonDict

    # Sandbox reuse (analogous to /new command).
    reuse_sandbox: bool
    sandbox_cache: JsonDict  # model -> sandbox_id mapping

    # Stage 2 development workflow controls.
    current_role: str
    pending_role: str | None
    pending_role_instance: str | None
    current_iteration: int
    max_fix_iterations: int
    next_node: str | None

    # Accumulated graph outputs.
    role_results: list[JsonDict]
    last_role_result: JsonDict | None
    scout_result: JsonDict | None
    research_result: JsonDict | None
    senior_staff_engineer_result: JsonDict | None
    architect_result: JsonDict | None
    coder_result: JsonDict | None
    qa_result: JsonDict | None
    reviewer_result: JsonDict | None
    publisher_result: JsonDict | None
    # Latest discovered validation profile / required target contract.
    # This is an input to Team Lead policy decisions, not an automatic gate.
    validation_profile: JsonDict | None
    team_lead_result: JsonDict | None
    team_lead_decision: JsonDict | None
    team_lead_steps: int
    max_team_lead_steps: int
    role_sessions: JsonDict
    final_answer: str | None
    final_status: str | None
    errors: list[str]

    # Human-readable/JSON-safe runtime metrics. These are best-effort
    # observability fields; routing must not depend on them.
    last_role_metrics: JsonDict | None
    workflow_metrics: JsonDict | None
