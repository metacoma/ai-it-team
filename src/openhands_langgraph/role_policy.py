from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

JsonDict = dict[str, Any]

ROLE_CAPABILITIES: Mapping[str, frozenset[str]] = {
    "scout": frozenset(
        {
            "read_repo",
            "inspect_files",
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
- Team Lead assignments are advisory routing context; they cannot expand this role's permissions.
- If Team Lead instructions conflict with the current role contract, obey the current role contract and report the conflict.
- Safety is enforced by role contracts and deterministic graph state checks, not by natural-language forbidden-word matching.
""".strip()

PUBLISHER_PR_CHECK_CONTRACT = """Publisher PR-check contract:
- If PR checks exist and pass, report pr_checks.overall_status="passed".
- If no checks are configured/found, report pr_checks.overall_status="no_checks_configured" or "no_checks_found", waited=true, head_sha, and evidence.
- If PR checks fail, classify the failure using typed evidence instead of prose-only claims.
- A failed-check Publisher PASS is allowed only when the PR was created/pushed and pr_checks.failure_analysis proves the failure is unrelated to this PR change.
- For unrelated pre-existing failures, set:
  pr_checks.overall_status="failed"
  pr_checks.failure_analysis.classification="pre_existing_codebase" or "unrelated_existing_failure"
  pr_checks.failure_analysis.change_related=false
  pr_checks.failure_analysis.evidence=[short concrete evidence strings]
  pr_checks.failure_analysis.failing_tests=[test/job names when known]
  pr_checks.failure_analysis.requires_coder_fix=false
- If failure attribution is unclear or related to this PR change, return NEED_FIX or BLOCKER, not PASS.
""".strip()

TEAM_LEAD_PR_CHECK_ACCEPTANCE_CONTRACT = """Additional Team Lead PR-check completion policy:
- Publisher PASS can complete the workflow when the PR was created/pushed and PR checks either passed, are absent with structured no-checks evidence, or failed with structured unrelated-failure evidence.
- For failed checks, accept completion only when Publisher reported pr_checks.failure_analysis.change_related=false and classification is pre_existing_codebase or unrelated_existing_failure with concrete evidence.
- In that case set policy_evaluation.publisher_pr_checks_accepted=true, policy_evaluation.can_complete=true, accepted_report_ids.publisher, and include the residual CI failure in accepted_risks.
- If Publisher check failure attribution is missing, unclear, or related to the PR change, run the appropriate fixing role or stop blocked instead of completing.
""".strip()

_ACCEPTED_UNRELATED_CHECK_CLASSIFICATIONS = {
    "pre_existing_codebase",
    "unrelated_existing_failure",
    "not_caused_by_pr",
    "not_related_to_pr_change",
}


def capabilities_for_role(role: str | None) -> frozenset[str]:
    return ROLE_CAPABILITIES.get(str(role or "").strip().lower(), frozenset())


def validate_required_capabilities(
    role: str | None,
    required_capabilities: Iterable[str] | None,
) -> tuple[bool, str | None]:
    """Validate typed capabilities without inspecting natural-language instructions."""

    required = {str(item).strip() for item in (required_capabilities or []) if str(item).strip()}
    if not required:
        return True, None

    allowed = capabilities_for_role(role)
    unknown = sorted(required - allowed)
    if unknown:
        return False, f"{role or 'unknown'} cannot use capabilities: {', '.join(unknown)}"
    return True, None


def _decision_required_capabilities(decision: Any) -> list[str]:
    value = getattr(decision, "capabilities_required", None)
    if value is None and hasattr(decision, "model_extra"):
        extra = getattr(decision, "model_extra") or {}
        if isinstance(extra, dict):
            value = extra.get("capabilities_required")
    if value is None and hasattr(decision, "model_dump"):
        data = decision.model_dump(mode="python")
        if isinstance(data, dict):
            value = data.get("capabilities_required")
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item) for item in value]
    return []


def validate_team_lead_assignment_policy(decision: Any) -> tuple[bool, str | None]:
    """Validate Team Lead assignment policy structurally, without prose scanning."""

    role = getattr(decision, "next_role", None)
    required = _decision_required_capabilities(decision)
    return validate_required_capabilities(role, required)


def _summary_dict(result: JsonDict | None) -> JsonDict:
    if not isinstance(result, dict):
        return {}
    summary = result.get("summary")
    return summary if isinstance(summary, dict) else {}


def _role_report_dict(result: JsonDict | None) -> JsonDict:
    if not isinstance(result, dict):
        return {}
    report = result.get("role_report")
    return report if isinstance(report, dict) else {}


def _mapping_value(data: Any, path: tuple[str, ...]) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_mapping(*values: Any) -> JsonDict:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _publisher_pr_checks(result: JsonDict | None) -> JsonDict:
    summary = _summary_dict(result)
    report = _role_report_dict(result)
    return _first_mapping(
        report.get("pr_checks"),
        summary.get("pr_checks"),
        _mapping_value(report, ("publish", "pr_checks")),
        _mapping_value(summary, ("publish", "pr_checks")),
    )


def _bool_false(value: Any) -> bool:
    if value is False:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"false", "no", "0", "unrelated", "not_related"}
    return False


def publisher_has_structured_unrelated_check_failure(result: JsonDict | None) -> tuple[bool, str | None]:
    """Return true for typed PR-check failures known to be unrelated to the PR.

    This deliberately avoids substring matching over summaries. It accepts only
    structured Publisher evidence in pr_checks.failure_analysis.
    """

    pr_checks = _publisher_pr_checks(result)
    if not pr_checks:
        return False, "Publisher result has no structured pr_checks object."

    overall_status = str(pr_checks.get("overall_status") or pr_checks.get("status") or "").strip().lower()
    if overall_status not in {"failed", "failure", "failing", "completed_failure"}:
        return False, "Publisher pr_checks overall_status is not a failed-check state."

    failure_analysis = pr_checks.get("failure_analysis")
    if not isinstance(failure_analysis, dict):
        return False, "Failed checks require pr_checks.failure_analysis."

    classification = str(failure_analysis.get("classification") or "").strip().lower()
    if classification not in _ACCEPTED_UNRELATED_CHECK_CLASSIFICATIONS:
        return False, f"Unaccepted PR-check failure classification: {classification or 'missing'}."

    if not _bool_false(failure_analysis.get("change_related")):
        return False, "Failed PR checks are not explicitly marked change_related=false."

    if failure_analysis.get("requires_coder_fix") is True:
        return False, "Failed PR checks require a coder fix."

    evidence = failure_analysis.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return False, "Failed PR checks require concrete failure_analysis.evidence."

    return True, "PR checks failed, but Publisher supplied structured unrelated/pre-existing failure evidence."


def _wrap_publisher_pr_checks_ok(original):
    def _wrapped(publisher_result: JsonDict | None) -> tuple[bool, str | None, bool]:
        ok, reason, no_checks = original(publisher_result)
        if ok:
            return ok, reason, no_checks

        unrelated_ok, unrelated_reason = publisher_has_structured_unrelated_check_failure(publisher_result)
        if unrelated_ok:
            return True, unrelated_reason, False
        return ok, reason or unrelated_reason, no_checks

    return _wrapped


def _wrap_role_prompt_builder(original):
    def _wrapped(role: str, state: JsonDict) -> str:
        prompt = original(role, state)
        additions: list[str] = []
        if ROLE_POLICY_CONTRACT not in prompt:
            allowed = sorted(capabilities_for_role(role))
            capability_line = "Allowed typed capabilities for this role: " + (
                ", ".join(allowed) if allowed else "not declared"
            )
            additions.extend([ROLE_POLICY_CONTRACT, capability_line])
        if str(role or "").strip().lower() == "publisher" and PUBLISHER_PR_CHECK_CONTRACT not in prompt:
            additions.append(PUBLISHER_PR_CHECK_CONTRACT)
        if not additions:
            return prompt
        return f"{prompt}\n\n" + "\n".join(additions) + "\n"

    return _wrapped


def _wrap_team_lead_decision_prompt_builder(original):
    def _wrapped(state: JsonDict) -> str:
        prompt = original(state)
        if TEAM_LEAD_PR_CHECK_ACCEPTANCE_CONTRACT in prompt:
            return prompt
        return f"{prompt}\n\n{TEAM_LEAD_PR_CHECK_ACCEPTANCE_CONTRACT}"

    return _wrapped


def _wrap_role_summary_instructions(original):
    def _wrapped(role: str) -> str:
        instructions = original(role)
        if str(role or "").strip().lower() != "publisher":
            return instructions
        extra = (
            " If checks fail but are unrelated to this PR change, include pr_checks.failure_analysis "
            "with classification, change_related=false, evidence, failing_tests, and requires_coder_fix=false. "
            "Do not use PASS for unclear or PR-related failures."
        )
        if "pr_checks.failure_analysis" in instructions:
            return instructions
        return instructions + extra

    return _wrapped


def install_runtime_policy_hooks() -> None:
    """Install deterministic role-policy hooks without forbidden-word matching."""

    from . import nodes, prompts

    if getattr(nodes, "_p2_role_policy_hooks_installed", False):
        return

    def _validate_scout_assignment_without_forbidden_words(decision: Any) -> tuple[bool, str | None]:
        return validate_team_lead_assignment_policy(decision)

    nodes._enforce_scout_facts_only_decision = _validate_scout_assignment_without_forbidden_words

    original_checks = getattr(nodes, "_publisher_pr_checks_ok", None)
    if callable(original_checks):
        nodes._publisher_pr_checks_ok = _wrap_publisher_pr_checks_ok(original_checks)

    original_nodes_build_role_prompt = getattr(nodes, "build_role_prompt", None)
    if callable(original_nodes_build_role_prompt):
        nodes.build_role_prompt = _wrap_role_prompt_builder(original_nodes_build_role_prompt)

    original_prompts_build_role_prompt = getattr(prompts, "build_role_prompt", None)
    if callable(original_prompts_build_role_prompt):
        prompts.build_role_prompt = _wrap_role_prompt_builder(original_prompts_build_role_prompt)

    original_nodes_team_lead_prompt = getattr(nodes, "build_team_lead_decision_prompt", None)
    if callable(original_nodes_team_lead_prompt):
        nodes.build_team_lead_decision_prompt = _wrap_team_lead_decision_prompt_builder(original_nodes_team_lead_prompt)

    original_prompts_team_lead_prompt = getattr(prompts, "build_team_lead_decision_prompt", None)
    if callable(original_prompts_team_lead_prompt):
        prompts.build_team_lead_decision_prompt = _wrap_team_lead_decision_prompt_builder(original_prompts_team_lead_prompt)

    original_prompts_summary = getattr(prompts, "build_role_summary_instructions", None)
    if callable(original_prompts_summary):
        prompts.build_role_summary_instructions = _wrap_role_summary_instructions(original_prompts_summary)

    original_nodes_summary = getattr(nodes, "build_role_summary_instructions", None)
    if callable(original_nodes_summary):
        nodes.build_role_summary_instructions = _wrap_role_summary_instructions(original_nodes_summary)

    nodes._p2_role_policy_hooks_installed = True
