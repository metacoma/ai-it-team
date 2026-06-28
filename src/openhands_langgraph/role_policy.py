from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

JsonDict = dict[str, Any]

# This module is intentionally a small compatibility layer over the existing
# Team Lead validator in nodes.py. It removes prose/text gates from routing
# validation and adds a typed direct-publisher path for release/tag-only work.
#
# The rest of the deterministic workflow gates in nodes.py remain intact:
# accepted report IDs, retry-after-runtime-failure, research/architect/QA/
# reviewer/publisher evidence gates, PR check validation, etc. Those gates
# validate workflow state and evidence, not natural-language wording.

ROLE_POLICY_HOOK_VERSION = 4

ROLE_CAPABILITIES: Mapping[str, frozenset[str]] = {
    "scout": frozenset(
        {
            "read_repo",
            "inspect_files",
            "inspect_git_history",
            "inspect_issue_metadata",
            "inspect_ci_metadata",
            "inspect_runtime_metadata",
            "inspect_publication_target",
            "summarize_facts",
            "identify_research_domains",
            "identify_validation_targets",
            "identify_documentation_targets",
            "report_unknowns",
        }
    ),
    "research": frozenset(
        {
            "web_search",
            "read_docs",
            "crawl_docs",
            "summarize_external_constraints",
            "summarize_best_practices",
            "verify_external_api_contract",
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
            "assess_documentation_impact",
        }
    ),
    "architect": frozenset(
        {
            "read_repo",
            "design_plan",
            "define_acceptance_criteria",
            "define_validation_plan",
            "assess_documentation_impact",
            "define_documentation_targets",
        }
    ),
    "coder": frozenset(
        {
            "read_repo",
            "edit_files",
            "install_deps",
            "run_validation",
            "assess_documentation_impact",
            "update_documentation",
            "summarize_changes",
        }
    ),
    "qa": frozenset(
        {
            "read_repo",
            "install_validation_deps",
            "run_validation",
            "inspect_test_results",
            "validate_documentation",
            "summarize_validation",
        }
    ),
    "reviewer": frozenset(
        {
            "read_repo",
            "inspect_diff",
            "run_lightweight_checks",
            "review_risk",
            "review_documentation",
            "summarize_review",
        }
    ),
    "publisher": frozenset(
        {
            "read_repo",
            "commit",
            "push",
            "create_pr",
            "create_tag",
            "create_release",
            "update_release_description",
            "inspect_release_artifacts",
            "monitor_workflow",
            "inspect_pr_checks",
            "classify_pr_check_failures",
            "publish_comment",
            "publish_discussion_comment",
            "publish_issue_comment",
            "publish_release_announcement",
            "bounded_external_publication",
            "summarize_publish_result",
        }
    ),
}

ROLE_POLICY_CONTRACT = """
Role policy contract:
- Team Lead assignments are routing context; they cannot expand a role's permissions.
- Deterministic assignment validation checks typed capabilities only, not natural-language words.
- Free-form instructions are human-readable guidance, not a policy source of truth.
- Words such as push, commit, PR, fix, build, implementation, release, or resolution may appear as factual objects being inspected or documented.
- If instructions and typed capabilities conflict, the role contract wins and the role must report the conflict.
""".strip()

TEAM_LEAD_ASSIGNMENT_CONTRACT = """
Additional Team Lead assignment contract:
- For RUN_ROLE and RETRY_ROLE decisions, capabilities_required is optional.
- If capabilities_required is present, it must contain only capabilities allowed for next_role.
- Do not rely on wording in instructions to express permissions or restrictions.
- Natural-language instructions are not structurally rejected for mentioning repository concepts such as push events, commits, PRs, releases, fixes, build files, implementation history, or issue resolution.
- Put future-role work in future_workflow_plan, but the deterministic validator will not reject current instructions by keyword.
- Team Lead must classify each task into work_order before routing specialist roles.
- Publisher normally follows implementation evidence from Coder/QA/Reviewer for repository work orders.
- For repository/repo_change work orders after Coder PASS, documentation impact must be assessed before publishing/completion. Documentation is either updated or explicitly waived with a concrete reason.
- For external_publication/direct_external_api tasks where repository changes are not required, Team Lead may route directly to Publisher after Scout/Research evidence is sufficient.
- Direct external publication without Coder PASS requires structured work_order and policy_evaluation acceptance: can_publish=true, no_repo_changes_accepted=true, publication_target_verified/target_verified=true, and publication_content_reviewed/content_prepared=true.
- Completion for external publication requires publisher_publication_evidence_accepted=true and structured publication evidence; it must not require PR/check evidence.
""".strip()

PUBLISHER_DIRECT_CODER_GATE_REASON = "Publisher cannot run before a usable Coder PASS"


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

    # Prefer direct attribute reads over model_dump(). Tests and runtime recovery
    # may assign plain dicts to pydantic fields; model_dump emits serializer
    # warnings for that compatibility path, while direct reads preserve exactly
    # what the validator needs.
    data: JsonDict = {}
    for key in (
        "action",
        "next_role",
        "capabilities_required",
        "assignment",
        "policy_evaluation",
        "accepted_report_ids",
        "workflow_mode",
        "work_order",
    ):
        if hasattr(decision, key):
            data[key] = getattr(decision, key)

    extra = getattr(decision, "model_extra", None)
    if isinstance(extra, dict):
        data.update(extra)

    if data:
        return data

    if hasattr(decision, "model_dump"):
        try:
            dumped = decision.model_dump(mode="python")
            return dict(dumped) if isinstance(dumped, Mapping) else {}
        except Exception:
            return {}

    return data


def _decision_policy(decision: Any) -> JsonDict:
    data = _decision_mapping(decision)
    policy = data.get("policy_evaluation")
    return dict(policy) if isinstance(policy, Mapping) else {}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on", "pass", "accepted"}


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
    required = {
        str(item).strip()
        for item in (required_capabilities or [])
        if str(item).strip()
    }
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


def _assignment_scope_without_prose_gate(decision: Any) -> tuple[bool, str | None]:
    """Replacement for nodes._assignment_scope_ok.

    The old implementation scanned free-form instructions for words like
    "push", "commit", "pull request", and "GITHUB_TOKEN". That caused false
    positives for legitimate research/scout tasks such as GitHub Actions
    ``on: push`` events or PR changelog generation. Assignment policy should
    be typed-capability based, so this function intentionally ignores prose.
    """
    return validate_team_lead_assignment_policy(decision)


def _scout_assignment_without_prose_gate(decision: Any) -> tuple[bool, str | None]:
    """Replacement for nodes._enforce_scout_facts_only_decision.

    Scout can mention issue resolution, commits, PRs, fixes, build files, or
    implementation history when the assignment is factual discovery. It should
    not be rejected by keyword; if explicit typed capabilities are provided,
    they are checked against Scout's capability set.
    """
    return validate_team_lead_assignment_policy(decision)


def _latest_pass_result_for_role(nodes_module: Any, state: JsonDict, role: str) -> JsonDict | None:
    helper = getattr(nodes_module, "_latest_pass_result_for_role", None)
    if callable(helper):
        result = helper(state, role)
        return result if isinstance(result, dict) and result else None

    for result in reversed(list(state.get("role_results") or [])):
        if not isinstance(result, dict):
            continue
        if str(result.get("role") or "").strip().lower() != role:
            continue
        if result.get("ok") is True and str(result.get("summary_action") or "").upper() == "PASS":
            return result
    direct = state.get(f"{role}_result")
    if isinstance(direct, dict) and direct.get("ok") is True:
        return direct
    return None


def _direct_publisher_without_coder_ok(
    nodes_module: Any,
    state: JsonDict,
    decision: Any,
) -> tuple[bool, str | None]:
    """Allow Publisher without Coder only for structurally accepted publish-only flow.

    This is intentionally not a prose scanner. It does not search for phrases
    like "no code changes". It relies on the Team Lead's structured policy
    fields plus a usable Scout PASS, and it only runs after the original
    validator already accepted earlier gates such as accepted_report_ids,
    retry requirements, research waiver, and assignment scope.
    """
    data = _decision_mapping(decision)
    next_role = str(data.get("next_role") or getattr(decision, "next_role", "")).strip().lower()
    if next_role != "publisher":
        return False, None

    if not _latest_pass_result_for_role(nodes_module, state, "scout"):
        return False, "Direct Publisher without Coder PASS requires a usable Scout PASS"

    policy = _decision_policy(decision)
    if _is_external_publication_decision(decision):
        required_policy_flags = ("can_publish", "no_repo_changes_accepted")
        missing = [flag for flag in required_policy_flags if not _truthy(policy.get(flag))]
        if not (_truthy(policy.get("publication_target_verified")) or _truthy(policy.get("target_verified"))):
            missing.append("publication_target_verified|target_verified")
        if not (_truthy(policy.get("publication_content_reviewed")) or _truthy(policy.get("content_prepared"))):
            missing.append("publication_content_reviewed|content_prepared")
        if missing:
            return (False, "Direct external Publisher without Coder PASS missing policy_evaluation flags: " + ", ".join(missing))
        return True, None

    required_policy_flags = (
        "can_publish",
        "can_skip_qa",
        "can_skip_reviewer",
        "qa_evidence_accepted",
        "reviewer_evidence_accepted",
    )
    missing = [flag for flag in required_policy_flags if not _truthy(policy.get(flag))]
    if missing:
        return (
            False,
            "Direct Publisher without Coder PASS requires policy_evaluation flags: "
            + ", ".join(required_policy_flags)
            + f"; missing/false: {', '.join(missing)}",
        )

    return True, None


def _wrap_team_lead_validator(original: Any) -> Any:
    if getattr(original, "_role_policy_wrapped", False):
        return original

    def _wrapped(state: JsonDict, decision: Any) -> tuple[bool, str | None]:
        ok, reason = original(state, decision)
        if ok:
            return ok, reason

        if reason == PUBLISHER_DIRECT_CODER_GATE_REASON:
            from . import nodes as nodes_module

            direct_ok, direct_error = _direct_publisher_without_coder_ok(
                nodes_module,
                state,
                decision,
            )
            if direct_ok:
                return True, None
            if direct_error:
                return False, direct_error

        return ok, reason

    _wrapped._role_policy_wrapped = True  # type: ignore[attr-defined]
    _wrapped._role_policy_original = original  # type: ignore[attr-defined]
    return _wrapped


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



def publisher_has_structured_unrelated_check_failure(result: JsonDict | None) -> tuple[bool, str | None]:
    """Return True when failed PR checks are explicitly attributed as unrelated.

    This is intentionally conservative: a failed check can be accepted by policy
    only if Publisher returned structured failure_analysis with change_related=false
    and requires_coder_fix=false. Team Lead still decides whether to accept it.
    """
    if not isinstance(result, Mapping):
        return False, "Publisher result is not a mapping"
    summary = result.get("summary") if isinstance(result.get("summary"), Mapping) else {}
    checks = summary.get("pr_checks")
    if not isinstance(checks, Mapping):
        report = result.get("role_report") if isinstance(result.get("role_report"), Mapping) else {}
        checks = report.get("pr_checks") if isinstance(report.get("pr_checks"), Mapping) else {}
    if not isinstance(checks, Mapping) or not checks:
        return False, "Missing pr_checks"
    failing = checks.get("failing_checks") or checks.get("failed_checks") or []
    overall = str(checks.get("overall_status") or checks.get("status") or "").strip().lower()
    if not failing and overall not in {"failed", "failure", "error"}:
        return False, "No failed checks were reported"
    analysis = checks.get("failure_analysis")
    if not isinstance(analysis, Mapping):
        return False, "Failed checks require structured failure_analysis"
    change_related = analysis.get("change_related")
    requires_coder_fix = analysis.get("requires_coder_fix")
    classification = str(analysis.get("classification") or "").strip().lower()
    evidence = analysis.get("evidence")
    if change_related is False and requires_coder_fix is False and evidence and classification in {
        "unrelated",
        "pre_existing",
        "pre-existing",
        "pre_existing_codebase",
        "external_flake",
        "infra_flake",
    }:
        return True, "failed checks are structured as unrelated/pre-existing"
    return False, "failure_analysis does not prove unrelated failed checks"


def _decision_work_order(decision: Any) -> JsonDict:
    data = _decision_mapping(decision)
    value = data.get("work_order")
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(mode="python")
            return dict(dumped) if isinstance(dumped, Mapping) else {}
        except Exception:
            return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _is_external_publication_decision(decision: Any) -> bool:
    work_order = _decision_work_order(decision)
    surface = str(work_order.get("change_surface") or "").strip().lower()
    strategy = str(work_order.get("execution_strategy") or "").strip().lower()
    return surface == "external_publication" or strategy == "direct_external_api"

def install_runtime_policy_hooks() -> None:
    """Install role-policy hooks and disable prose-based Team Lead gates.

    This function is idempotent, but it also upgrades installations that had
    earlier v1/v2 hooks where only prose scanners were replaced.
    """
    from . import nodes, prompts

    installed_version = int(getattr(nodes, "_role_policy_hooks_installed_version", 0) or 0)
    if installed_version >= ROLE_POLICY_HOOK_VERSION:
        return

    # Remove natural-language gates from Team Lead structural validation.
    # Keep all evidence/state-based gates implemented in nodes.py.
    nodes._assignment_scope_ok = _assignment_scope_without_prose_gate
    nodes._enforce_scout_facts_only_decision = _scout_assignment_without_prose_gate

    original_validator = getattr(nodes, "_validate_team_lead_decision", None)
    if callable(original_validator):
        nodes._validate_team_lead_decision = _wrap_team_lead_validator(original_validator)

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

    nodes._role_policy_hooks_installed = True
    nodes._role_policy_hooks_installed_version = ROLE_POLICY_HOOK_VERSION
