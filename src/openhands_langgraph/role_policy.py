from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

JsonDict = dict[str, Any]

ROLE_CAPABILITIES: Mapping[str, frozenset[str]] = {
    "scout": frozenset(
        {
            "read_repo",
            "inspect_files",
            "inspect_git_history",
            "inspect_issue_metadata",
            "inspect_ci_metadata",
            "inspect_runtime_metadata",
            "summarize_facts",
            "identify_research_domains",
            "identify_validation_targets",
            "report_unknowns",
        }
    ),
    "research": frozenset(
        {
            "web_search",
            "read_docs",
            "summarize_external_constraints",
            "summarize_best_practices",
            "report_unknowns",
        }
    ),
    "senior_staff_engineer": frozenset(
        {
            "read_repo",
            "analyze_risk",
            "define_strategy",
            "define_acceptance_criteria",
            "define_validation_plan",
        }
    ),
    "architect": frozenset(
        {
            "read_repo",
            "design_plan",
            "define_acceptance_criteria",
            "define_validation_plan",
        }
    ),
    "coder": frozenset(
        {
            "read_repo",
            "edit_files",
            "install_deps",
            "run_validation",
            "summarize_changes",
        }
    ),
    "qa": frozenset(
        {
            "read_repo",
            "install_validation_deps",
            "run_validation",
            "inspect_test_results",
            "summarize_validation",
        }
    ),
    "reviewer": frozenset(
        {
            "read_repo",
            "inspect_diff",
            "run_lightweight_checks",
            "review_risk",
            "summarize_review",
        }
    ),
    "publisher": frozenset(
        {
            "read_repo",
            "commit",
            "push",
            "create_pr",
            "inspect_pr_checks",
            "classify_pr_check_failures",
            "summarize_publish_result",
        }
    ),
}

ROLE_POLICY_CONTRACT = """Role policy contract:
- Team Lead assignments are routing context; they cannot expand a role's permissions.
- Deterministic validation checks typed capabilities only, not natural-language words.
- Free-form instructions are human-readable guidance, not a policy source of truth.
- If instructions and typed capabilities conflict, the role contract wins and the role must report the conflict.
""".strip()

TEAM_LEAD_ASSIGNMENT_CONTRACT = """Additional Team Lead assignment contract:
- For RUN_ROLE decisions, include an optional capabilities_required list.
- capabilities_required must contain only capabilities allowed for next_role.
- Do not rely on wording in instructions to express permissions or restrictions.
- Scout factual work can mention issue resolution, commits, PRs, fixes, implementation history, or build files when the task is to inspect facts; this is not an instruction to modify code or run validation.
""".strip()


def capabilities_for_role(role: str | None) -> frozenset[str]:
    return ROLE_CAPABILITIES.get(str(role or "").strip().lower(), frozenset())


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        item = value.strip()
        return [item] if item else []
    if isinstance(value, Mapping):
        return []
    if isinstance(value, Iterable):
        result: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text:
                result.append(text)
        return result
    return []


def _mapping_get_any(data: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _decision_mapping(decision: Any) -> JsonDict:
    if isinstance(decision, dict):
        return dict(decision)
    if hasattr(decision, "model_dump"):
        try:
            data = decision.model_dump(mode="python")
            if isinstance(data, dict):
                return dict(data)
        except Exception:
            pass
    data: JsonDict = {}
    for key in ("action", "next_role", "capabilities_required", "assignment"):
        if hasattr(decision, key):
            data[key] = getattr(decision, key)
    extra = getattr(decision, "model_extra", None)
    if isinstance(extra, dict):
        data.update(extra)
    return data


def decision_required_capabilities(decision: Any) -> list[str]:
    data = _decision_mapping(decision)
    required = _as_string_list(
        _mapping_get_any(
            data,
            "capabilities_required",
            "required_capabilities",
            "allowed_capabilities",
        )
    )
    assignment = data.get("assignment")
    if isinstance(assignment, Mapping):
        required.extend(
            _as_string_list(
                _mapping_get_any(
                    assignment,
                    "capabilities_required",
                    "required_capabilities",
                    "allowed_capabilities",
                    "allowed_operations",
                    "operations",
                )
            )
        )
    seen: set[str] = set()
    normalized: list[str] = []
    for item in required:
        capability = item.strip()
        if capability and capability not in seen:
            seen.add(capability)
            normalized.append(capability)
    return normalized


def validate_required_capabilities(
    role: str | None,
    required_capabilities: Iterable[str] | None,
) -> tuple[bool, str | None]:
    required = {str(item).strip() for item in (required_capabilities or []) if str(item).strip()}
    if not required:
        return True, None
    allowed = capabilities_for_role(role)
    forbidden = sorted(required - allowed)
    if forbidden:
        return False, f"{role or 'unknown'} cannot use capabilities: {', '.join(forbidden)}"
    return True, None


def validate_team_lead_assignment_policy(decision: Any) -> tuple[bool, str | None]:
    data = _decision_mapping(decision)
    role = data.get("next_role") or getattr(decision, "next_role", None)
    return validate_required_capabilities(role, decision_required_capabilities(decision))


def _wrap_role_prompt_builder(original: Any) -> Any:
    if getattr(original, "_role_policy_wrapped", False):
        return original

    def _wrapped(role: str, state: JsonDict) -> str:
        prompt = original(role, state)
        additions: list[str] = []
        if ROLE_POLICY_CONTRACT not in prompt:
            allowed = sorted(capabilities_for_role(role))
            capability_line = "Allowed typed capabilities for this role: " + (
                ", ".join(allowed) if allowed else "not declared"
            )
            additions.extend([ROLE_POLICY_CONTRACT, capability_line])
        if not additions:
            return prompt
        return f"{prompt}\n\n" + "\n".join(additions) + "\n"

    _wrapped._role_policy_wrapped = True  # type: ignore[attr-defined]
    return _wrapped


def _wrap_team_lead_decision_prompt_builder(original: Any) -> Any:
    if getattr(original, "_role_policy_wrapped", False):
        return original

    def _wrapped(state: JsonDict) -> str:
        prompt = original(state)
        if TEAM_LEAD_ASSIGNMENT_CONTRACT in prompt:
            return prompt
        capability_lines = ["Allowed typed capabilities by role:"]
        for role, caps in sorted(ROLE_CAPABILITIES.items()):
            capability_lines.append(f"- {role}: {', '.join(sorted(caps))}")
        return f"{prompt}\n\n{TEAM_LEAD_ASSIGNMENT_CONTRACT}\n" + "\n".join(capability_lines)

    _wrapped._role_policy_wrapped = True  # type: ignore[attr-defined]
    return _wrapped


def _wrap_structural_team_lead_validator(original: Any) -> Any:
    if getattr(original, "_role_policy_wrapped", False):
        return original

    def _wrapped(decision: Any, state: JsonDict | None = None):
        result = original(decision, state) if state is not None else original(decision)
        ok, reason = validate_team_lead_assignment_policy(decision)
        if ok:
            return result
        if isinstance(result, tuple):
            if len(result) == 2:
                return False, reason
            if len(result) == 3:
                return False, reason, result[2]
        return False, reason

    _wrapped._role_policy_wrapped = True  # type: ignore[attr-defined]
    return _wrapped


def install_runtime_policy_hooks() -> None:
    """Install deterministic role-policy hooks without forbidden-word matching.

    This deliberately overrides the old Scout prose scanner. The replacement
    checks typed capabilities only, so words such as "resolution" or
    "implementation history" cannot accidentally block a factual Scout task.
    """
    from . import nodes, prompts

    if getattr(nodes, "_role_policy_hooks_installed", False):
        return

    def _validate_scout_assignment_without_prose_scanning(decision: Any) -> tuple[bool, str | None]:
        return validate_team_lead_assignment_policy(decision)

    nodes._enforce_scout_facts_only_decision = _validate_scout_assignment_without_prose_scanning

    original_nodes_role_prompt = getattr(nodes, "build_role_prompt", None)
    if callable(original_nodes_role_prompt):
        nodes.build_role_prompt = _wrap_role_prompt_builder(original_nodes_role_prompt)

    original_prompts_role_prompt = getattr(prompts, "build_role_prompt", None)
    if callable(original_prompts_role_prompt):
        prompts.build_role_prompt = _wrap_role_prompt_builder(original_prompts_role_prompt)

    original_nodes_team_lead_prompt = getattr(nodes, "build_team_lead_decision_prompt", None)
    if callable(original_nodes_team_lead_prompt):
        nodes.build_team_lead_decision_prompt = _wrap_team_lead_decision_prompt_builder(
            original_nodes_team_lead_prompt
        )

    original_prompts_team_lead_prompt = getattr(prompts, "build_team_lead_decision_prompt", None)
    if callable(original_prompts_team_lead_prompt):
        prompts.build_team_lead_decision_prompt = _wrap_team_lead_decision_prompt_builder(
            original_prompts_team_lead_prompt
        )

    # Some local versions have a separate Team Lead structural validator.
    # Patch it when present, but do not require it for compatibility.
    original_validator = getattr(nodes, "_validate_team_lead_decision", None)
    if callable(original_validator):
        nodes._validate_team_lead_decision = _wrap_structural_team_lead_validator(original_validator)

    nodes._role_policy_hooks_installed = True
