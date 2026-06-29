from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RoleSpec:
    """Declarative role contract used by Team Lead routing and prompts.

    New specialist roles should be added here first. The graph can keep the same
    Team Lead -> dynamic role executor shape while routing and validation learn
    about the new role through this catalog instead of hard-coded pipeline order.
    """

    name: str
    title: str
    category: str
    description: str
    capabilities: frozenset[str]
    change_surfaces: frozenset[str]
    can_mutate: bool = False
    mutation_surfaces: frozenset[str] = frozenset()

    def capability_line(self) -> str:
        caps = ", ".join(sorted(self.capabilities)) if self.capabilities else "none declared"
        return f"- {self.name}: {self.description} Capabilities: {caps}."

    def role_contract(self) -> str:
        allowed = ", ".join(sorted(self.capabilities)) if self.capabilities else "not declared"
        surfaces = ", ".join(sorted(self.change_surfaces)) if self.change_surfaces else "none declared"
        mutations = ", ".join(sorted(self.mutation_surfaces)) if self.mutation_surfaces else "none"
        return (
            "Role catalog contract:\n"
            f"- role: {self.name}\n"
            f"- category: {self.category}\n"
            f"- can_mutate: {str(self.can_mutate).lower()}\n"
            f"- supported_change_surfaces: {surfaces}\n"
            f"- mutation_surfaces: {mutations}\n"
            f"- allowed_typed_capabilities: {allowed}\n"
            "- Team Lead assignments cannot expand this contract. If instructions conflict with this contract, follow the contract and report the conflict."
        )


ROLE_CATALOG: Mapping[str, RoleSpec] = {
    "scout": RoleSpec(
        name="scout",
        title="Scout / Repository Fact Finder",
        category="discovery",
        description="read-only repository/workspace/log context discovery; facts only; no writes, tests, builds, installs, commits, pushes, or PRs.",
        capabilities=frozenset(
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
        change_surfaces=frozenset({"none", "repository", "external_publication", "live_server", "kubernetes_cluster", "monitoring", "database", "network", "security", "unknown"}),
    ),
    "research": RoleSpec(
        name="research",
        title="Research / Current Documentation Researcher",
        category="discovery",
        description="external best-practice and target-runtime research; uses local-docs/searxNcrawl when current docs matter; no repository or live writes.",
        capabilities=frozenset(
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
        change_surfaces=frozenset({"none", "repository", "external_publication", "live_server", "kubernetes_cluster", "monitoring", "database", "network", "security", "unknown"}),
    ),
    "senior_staff_engineer": RoleSpec(
        name="senior_staff_engineer",
        title="Senior Staff Engineer / Strategy Gate",
        category="planning",
        description="execution contract, assumption ledger, risk strategy, and acceptance criteria; no repository or live writes.",
        capabilities=frozenset(
            {
                "read_repo",
                "analyze_risk",
                "define_strategy",
                "define_acceptance_criteria",
                "define_validation_plan",
                "assess_documentation_impact",
            }
        ),
        change_surfaces=frozenset({"repository", "live_server", "kubernetes_cluster", "monitoring", "database", "network", "security", "unknown"}),
    ),
    "architect": RoleSpec(
        name="architect",
        title="Architect / Implementation Planner",
        category="planning",
        description="read-only implementation/configuration plan, validation plan, and documentation impact; no writes or execution.",
        capabilities=frozenset(
            {
                "read_repo",
                "design_plan",
                "define_acceptance_criteria",
                "define_validation_plan",
                "assess_documentation_impact",
                "define_documentation_targets",
            }
        ),
        change_surfaces=frozenset({"repository", "live_server", "kubernetes_cluster", "monitoring", "database", "network", "security", "unknown"}),
    ),
    "coder": RoleSpec(
        name="coder",
        title="Coder / Implementation Engineer",
        category="executor",
        description="local repository implementation and relevant self-validation; may edit workspace files but must not publish.",
        capabilities=frozenset(
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
        change_surfaces=frozenset({"repository", "monitoring", "security", "unknown"}),
        can_mutate=True,
        mutation_surfaces=frozenset({"repository"}),
    ),
    "qa": RoleSpec(
        name="qa",
        title="QA / Validation Engineer",
        category="control",
        description="validates concrete implementation/configuration artifacts; may install validation tooling but must not implement or publish.",
        capabilities=frozenset(
            {
                "read_repo",
                "install_validation_deps",
                "run_validation",
                "inspect_test_results",
                "validate_documentation",
                "summarize_validation",
            }
        ),
        change_surfaces=frozenset({"repository", "live_server", "kubernetes_cluster", "monitoring", "database", "network", "security", "unknown"}),
    ),
    "reviewer": RoleSpec(
        name="reviewer",
        title="Reviewer / Independent Quality Gate",
        category="control",
        description="independent diff/risk/documentation review; no implementation or publication.",
        capabilities=frozenset(
            {
                "read_repo",
                "inspect_diff",
                "run_lightweight_checks",
                "review_risk",
                "review_documentation",
                "summarize_review",
            }
        ),
        change_surfaces=frozenset({"repository", "live_server", "kubernetes_cluster", "monitoring", "database", "network", "security", "unknown"}),
    ),
    "publisher": RoleSpec(
        name="publisher",
        title="Publisher / Delivery Publisher",
        category="delivery",
        description="delivery-only role; the only role allowed to commit/push/create PRs or perform bounded external publication actions when assigned; must not debug/fix failed checks or edit implementation/docs/tests/config.",
        capabilities=frozenset(
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
                "collect_pr_check_failure_evidence",
                "publish_comment",
                "publish_discussion_comment",
                "publish_issue_comment",
                "publish_release_announcement",
                "bounded_external_publication",
                "summarize_publish_result",
            }
        ),
        change_surfaces=frozenset({"repository", "external_publication", "unknown"}),
        can_mutate=True,
        mutation_surfaces=frozenset({"repository", "external_publication", "github"}),
    ),
}

TEAM_LEAD_ALLOWED_ROLES = frozenset(ROLE_CATALOG)
ROLE_CAPABILITIES: Mapping[str, frozenset[str]] = {
    role: spec.capabilities for role, spec in ROLE_CATALOG.items()
}


def role_spec(role: str | None) -> RoleSpec | None:
    return ROLE_CATALOG.get(str(role or "").strip().lower())


def capabilities_for_role(role: str | None) -> frozenset[str]:
    spec = role_spec(role)
    return spec.capabilities if spec else frozenset()


def role_supports_surface(role: str | None, surface: str | None) -> bool:
    spec = role_spec(role)
    if not spec:
        return False
    normalized = str(surface or "unknown").strip().lower() or "unknown"
    return normalized in spec.change_surfaces or "unknown" in spec.change_surfaces


def capability_matrix_text() -> str:
    lines = ["Allowed specialist roles / capability matrix:"]
    for role in sorted(ROLE_CATALOG):
        lines.append(ROLE_CATALOG[role].capability_line())
    return "\n".join(lines)


def allowed_roles_json_hint() -> str:
    return " | ".join(sorted(TEAM_LEAD_ALLOWED_ROLES))


def role_contract_footer(role: str | None) -> str:
    spec = role_spec(role)
    if not spec:
        return (
            "Role catalog contract:\n"
            f"- role: {role or 'unknown'}\n"
            "- allowed_typed_capabilities: not declared\n"
            "- If this is a future role, add it to role_catalog.py before relying on it in policy validation."
        )
    return spec.role_contract()
