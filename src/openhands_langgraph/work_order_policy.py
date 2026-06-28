from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .role_catalog import TEAM_LEAD_ALLOWED_ROLES, capabilities_for_role, role_supports_surface

JsonDict = dict[str, Any]

WORK_ORDER_SURFACES = frozenset(
    {
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
    }
)
EXECUTION_STRATEGIES = frozenset(
    {
        "answer_only",
        "repo_change",
        "direct_external_api",
        "direct_live_execution",
        "iac_or_gitops",
        "investigation_only",
        "unknown",
    }
)


@dataclass(frozen=True)
class WorkOrderSurfacePolicy:
    """Deterministic routing policy for a class of work.

    This is the extension point for future roles. Add a new role to
    role_catalog.py, then adjust the relevant surface policy here only when the
    surface itself needs different gates.
    """

    surface: str
    description: str
    delivery_role: str | None
    requires_repository_chain: bool = False
    requires_documentation_gate: bool = False
    requires_pr_checks: bool = False
    requires_publication_evidence: bool = False
    requires_discovery_before_delivery: bool = False
    allowed_execution_strategies: frozenset[str] = frozenset({"unknown"})
    forbidden_roles_without_repo_change: frozenset[str] = frozenset()
    required_evidence_hint: tuple[str, ...] = ()


SURFACE_POLICIES: Mapping[str, WorkOrderSurfacePolicy] = {
    "none": WorkOrderSurfacePolicy(
        surface="none",
        description="answer-only or analysis-only work without mutation",
        delivery_role=None,
        allowed_execution_strategies=frozenset({"answer_only", "investigation_only", "unknown"}),
        required_evidence_hint=("answer_or_report",),
    ),
    "repository": WorkOrderSurfacePolicy(
        surface="repository",
        description="repository file changes delivered through branch/PR/check evidence",
        delivery_role="publisher",
        requires_repository_chain=True,
        requires_documentation_gate=True,
        requires_pr_checks=True,
        allowed_execution_strategies=frozenset({"repo_change", "iac_or_gitops", "unknown"}),
        required_evidence_hint=("implementation_summary", "documentation_updated_or_waived", "tests_or_waiver", "review_or_waiver", "pr_checks"),
    ),
    "external_publication": WorkOrderSurfacePolicy(
        surface="external_publication",
        description="bounded write to an external collaboration system such as GitHub comments/discussions/issues",
        delivery_role="publisher",
        requires_publication_evidence=True,
        requires_discovery_before_delivery=True,
        allowed_execution_strategies=frozenset({"direct_external_api", "unknown"}),
        forbidden_roles_without_repo_change=frozenset({"coder", "qa", "reviewer"}),
        required_evidence_hint=("target_verified", "content_prepared", "publication_id_or_url"),
    ),
    "live_server": WorkOrderSurfacePolicy(
        surface="live_server",
        description="runtime mutation on a live host/server",
        delivery_role=None,
        requires_discovery_before_delivery=True,
        allowed_execution_strategies=frozenset({"direct_live_execution", "iac_or_gitops", "investigation_only", "unknown"}),
        required_evidence_hint=("target_verified", "readonly_discovery", "execution_plan", "rollback_plan", "execution_log", "postcheck"),
    ),
    "kubernetes_cluster": WorkOrderSurfacePolicy(
        surface="kubernetes_cluster",
        description="runtime or GitOps mutation affecting a Kubernetes cluster",
        delivery_role=None,
        requires_discovery_before_delivery=True,
        allowed_execution_strategies=frozenset({"direct_live_execution", "iac_or_gitops", "repo_change", "investigation_only", "unknown"}),
        required_evidence_hint=("context_verified", "manifest_or_command_plan", "dry_run_or_waiver", "rollout_status", "postcheck", "rollback_plan"),
    ),
    "monitoring": WorkOrderSurfacePolicy(
        surface="monitoring",
        description="alerting, dashboards, metrics, logs, or notification routing changes",
        delivery_role=None,
        requires_discovery_before_delivery=True,
        allowed_execution_strategies=frozenset({"repo_change", "direct_live_execution", "iac_or_gitops", "investigation_only", "unknown"}),
        required_evidence_hint=("alert_semantics_verified", "query_validated", "route_checked", "postcheck"),
    ),
    "database": WorkOrderSurfacePolicy(
        surface="database",
        description="database schema/runtime/data-adjacent operational work",
        delivery_role=None,
        requires_discovery_before_delivery=True,
        allowed_execution_strategies=frozenset({"direct_live_execution", "iac_or_gitops", "repo_change", "investigation_only", "unknown"}),
        required_evidence_hint=("target_verified", "backup_or_rollback", "migration_plan", "postcheck"),
    ),
    "network": WorkOrderSurfacePolicy(
        surface="network",
        description="network/firewall/DNS/routing operational work",
        delivery_role=None,
        requires_discovery_before_delivery=True,
        allowed_execution_strategies=frozenset({"direct_live_execution", "iac_or_gitops", "repo_change", "investigation_only", "unknown"}),
        required_evidence_hint=("target_verified", "current_state", "change_plan", "rollback_plan", "connectivity_postcheck"),
    ),
    "security": WorkOrderSurfacePolicy(
        surface="security",
        description="security-sensitive repository or operational work",
        delivery_role=None,
        requires_discovery_before_delivery=True,
        allowed_execution_strategies=frozenset({"repo_change", "direct_live_execution", "iac_or_gitops", "investigation_only", "unknown"}),
        required_evidence_hint=("threat_or_risk_assessed", "change_plan", "validation", "review"),
    ),
    "unknown": WorkOrderSurfacePolicy(
        surface="unknown",
        description="insufficiently classified work; discovery/planning required before mutation",
        delivery_role=None,
        requires_discovery_before_delivery=True,
        allowed_execution_strategies=frozenset({"unknown", "investigation_only"}),
        required_evidence_hint=("classification", "target_verified"),
    ),
}


def _as_mapping(value: Any) -> JsonDict:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(mode="python")
            return dict(dumped) if isinstance(dumped, Mapping) else {}
        except Exception:
            return {}
    return {}


def decision_mapping(decision: Any) -> JsonDict:
    if isinstance(decision, Mapping):
        return dict(decision)
    data: JsonDict = {}
    for key in (
        "action",
        "next_role",
        "capabilities_required",
        "assignment",
        "policy_evaluation",
        "accepted_report_ids",
        "work_order",
    ):
        if hasattr(decision, key):
            data[key] = getattr(decision, key)
    extra = getattr(decision, "model_extra", None)
    if isinstance(extra, Mapping):
        data.update(extra)
    if data:
        return data
    if hasattr(decision, "model_dump"):
        try:
            dumped = decision.model_dump(mode="python")
            return dict(dumped) if isinstance(dumped, Mapping) else {}
        except Exception:
            return {}
    return {}


def decision_policy(decision: Any) -> JsonDict:
    return _as_mapping(decision_mapping(decision).get("policy_evaluation"))


def decision_work_order(decision: Any) -> JsonDict:
    return _as_mapping(decision_mapping(decision).get("work_order"))


def normalize_surface(value: Any) -> str:
    surface = str(value or "unknown").strip().lower() or "unknown"
    return surface if surface in WORK_ORDER_SURFACES else "unknown"


def normalize_strategy(value: Any) -> str:
    strategy = str(value or "unknown").strip().lower() or "unknown"
    return strategy if strategy in EXECUTION_STRATEGIES else "unknown"


def work_order_surface(decision: Any) -> str:
    return normalize_surface(decision_work_order(decision).get("change_surface") or "repository")


def work_order_strategy(decision: Any) -> str:
    return normalize_strategy(decision_work_order(decision).get("execution_strategy") or "repo_change")


def surface_policy(surface: str | None) -> WorkOrderSurfacePolicy:
    return SURFACE_POLICIES.get(normalize_surface(surface), SURFACE_POLICIES["unknown"])


def is_repository_work_order(decision: Any) -> bool:
    return work_order_surface(decision) == "repository" or work_order_strategy(decision) == "repo_change"


def is_external_publication_order(decision: Any) -> bool:
    return work_order_surface(decision) == "external_publication" or work_order_strategy(decision) == "direct_external_api"


def work_order_forbidden_roles(decision: Any) -> set[str]:
    work_order = decision_work_order(decision)
    raw = work_order.get("forbidden_roles") or []
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.replace(";", ",").split(",")]
    if not isinstance(raw, Iterable) or isinstance(raw, Mapping):
        return set()
    return {str(item or "").strip().lower() for item in raw if str(item or "").strip()}


def work_order_forbids_role(decision: Any, role: str | None) -> bool:
    normalized = str(role or "").strip().lower()
    return bool(normalized and normalized in work_order_forbidden_roles(decision))


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Mapping):
        return []
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value).strip()
    return [text] if text else []


def decision_required_capabilities(decision: Any) -> list[str]:
    data = decision_mapping(decision)
    required = _as_string_list(
        data.get("capabilities_required")
        or data.get("required_capabilities")
        or data.get("allowed_capabilities")
    )
    assignment = data.get("assignment")
    if isinstance(assignment, Mapping):
        for key in ("capabilities_required", "required_capabilities", "allowed_capabilities", "allowed_operations", "operations"):
            required.extend(_as_string_list(assignment.get(key)))

    seen: set[str] = set()
    result: list[str] = []
    for item in required:
        capability = item.strip()
        if capability and capability not in seen:
            seen.add(capability)
            result.append(capability)
    return result


def validate_required_capabilities(role: str | None, required_capabilities: Iterable[str] | None) -> tuple[bool, str | None]:
    required = {str(item).strip() for item in (required_capabilities or []) if str(item).strip()}
    if not required:
        return True, None
    allowed = capabilities_for_role(role)
    forbidden = sorted(required - allowed)
    if forbidden:
        return False, f"{role or 'unknown'} cannot use capabilities: {', '.join(forbidden)}"
    return True, None


def validate_assignment_capabilities(decision: Any) -> tuple[bool, str | None]:
    data = decision_mapping(decision)
    role = data.get("next_role") or getattr(decision, "next_role", None)
    return validate_required_capabilities(role, decision_required_capabilities(decision))


def validate_work_order_role_selection(decision: Any, role: str | None) -> tuple[bool, str | None]:
    normalized_role = str(role or "").strip().lower()
    if not normalized_role:
        return False, "RUN_ROLE/RETRY_ROLE requires next_role"
    if normalized_role not in TEAM_LEAD_ALLOWED_ROLES:
        return False, f"unsupported Team Lead next_role: {normalized_role}"

    if work_order_forbids_role(decision, normalized_role):
        return False, f"Work order forbids role: {normalized_role}"

    surface = work_order_surface(decision)
    strategy = work_order_strategy(decision)
    policy = surface_policy(surface)
    if strategy not in policy.allowed_execution_strategies and "unknown" not in policy.allowed_execution_strategies:
        return False, f"Work order strategy {strategy} is not allowed for change_surface={surface}"

    if normalized_role in policy.forbidden_roles_without_repo_change:
        return False, f"{surface.replace('_', ' ')} work order must not route to {normalized_role} unless repository changes are required"

    # Discovery/control roles may support broad surfaces through "unknown" while
    # executor/delivery roles should declare the surface explicitly.
    if not role_supports_surface(normalized_role, surface):
        return False, f"Role {normalized_role} does not support work_order.change_surface={surface}"

    return validate_assignment_capabilities(decision)


def surface_policy_matrix_text() -> str:
    lines = ["Work-order surface policy matrix:"]
    for name in sorted(SURFACE_POLICIES):
        policy = SURFACE_POLICIES[name]
        strategies = ", ".join(sorted(policy.allowed_execution_strategies))
        evidence = ", ".join(policy.required_evidence_hint) or "task-specific evidence"
        gates: list[str] = []
        if policy.requires_repository_chain:
            gates.append("repository_chain")
        if policy.requires_documentation_gate:
            gates.append("documentation_gate")
        if policy.requires_pr_checks:
            gates.append("pr_checks")
        if policy.requires_publication_evidence:
            gates.append("publication_evidence")
        if policy.requires_discovery_before_delivery:
            gates.append("discovery_before_delivery")
        gates_text = ", ".join(gates) if gates else "none"
        lines.append(f"- {name}: strategies={strategies}; gates={gates_text}; evidence={evidence}")
    return "\n".join(lines)
