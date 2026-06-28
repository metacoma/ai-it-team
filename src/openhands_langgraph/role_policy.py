from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .role_catalog import ROLE_CAPABILITIES, capabilities_for_role, role_contract_footer
from .work_order_policy import (
    decision_required_capabilities,
    validate_assignment_capabilities,
    validate_required_capabilities,
)

JsonDict = dict[str, Any]

ROLE_POLICY_HOOK_VERSION = 5

ROLE_POLICY_CONTRACT = """
Role policy contract:
- Team Lead assignments are routing context; they cannot expand a role's permissions.
- Deterministic assignment validation checks typed capabilities and work_order policy, not natural-language words.
- Free-form instructions are human-readable guidance, not a policy source of truth.
- Words such as push, commit, PR, fix, build, implementation, release, or resolution may appear as factual objects being inspected or documented.
- If instructions and typed capabilities conflict, the role catalog contract wins and the role must report the conflict.
""".strip()

TEAM_LEAD_ASSIGNMENT_CONTRACT = """
Additional Team Lead assignment contract:
- For RUN_ROLE and RETRY_ROLE decisions, capabilities_required is optional but authoritative when present.
- If capabilities_required is present, every item must be owned by next_role in role_catalog.py.
- Do not rely on wording in instructions to express permissions or restrictions.
- Natural-language instructions are not structurally rejected for mentioning repository concepts such as push events, commits, PRs, releases, fixes, build files, implementation history, or issue resolution.
- Put future-role work in future_workflow_plan, but the deterministic validator will not reject current instructions by keyword.
- Team Lead must classify each task into work_order before routing specialist roles.
- Publisher normally follows implementation evidence from Coder/QA/Reviewer for repository work orders.
- For repository/repo_change work orders after Coder PASS, documentation impact must be assessed before publishing/completion. Documentation is either updated or explicitly waived with a concrete reason.
- For external_publication/direct_external_api tasks where repository changes are not required, Team Lead may route directly to Publisher after Scout/Research evidence is sufficient.
- Completion for external publication requires publisher_publication_evidence_accepted=true and structured publication evidence; it must not require PR/check evidence.
""".strip()


def validate_team_lead_assignment_policy(decision: Any) -> tuple[bool, str | None]:
    """Validate the selected role against typed capabilities.

    This function is kept as the public compatibility entry point used by tests
    and nodes.py, but the implementation is now part of the work-order policy
    engine instead of runtime monkeypatches.
    """

    return validate_assignment_capabilities(decision)


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


def install_runtime_policy_hooks() -> None:
    """Compatibility no-op.

    Older versions installed monkeypatches over nodes.py and prompts.py to make
    routing less fixed. The policy is now integrated directly through
    role_catalog.py and work_order_policy.py, so importing the package no longer
    mutates runtime functions.
    """

    return None


__all__ = [
    "ROLE_CAPABILITIES",
    "ROLE_POLICY_CONTRACT",
    "TEAM_LEAD_ASSIGNMENT_CONTRACT",
    "capabilities_for_role",
    "decision_required_capabilities",
    "install_runtime_policy_hooks",
    "publisher_has_structured_unrelated_check_failure",
    "role_contract_footer",
    "validate_required_capabilities",
    "validate_team_lead_assignment_policy",
]
