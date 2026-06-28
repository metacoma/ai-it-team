from __future__ import annotations

import json
from typing import Any

from .reports import compact_validation_profile

JsonDict = dict[str, Any]

PASS_ACTIONS = {"PASS", "COMPLETED", "DONE", "OK", "CONTINUE", "PLAN_READY", "PROCEED"}
NEED_FIX_ACTIONS = {"NEED_FIX", "FIX", "REWORK", "RETRY", "NEED_MORE_RESEARCH", "NEED_MORE_SCOUT"}
BLOCK_ACTIONS = {"BLOCKER", "BLOCK", "FAILED", "FAIL"}
TEAM_LEAD_RUN_ACTIONS = {"RUN_ROLE", "RETRY_ROLE"}
TEAM_LEAD_STOP_ACTIONS = {"STOP_COMPLETED", "STOP_BLOCKED", "ASK_HUMAN"}
TEAM_LEAD_ALLOWED_ROLES = {
    "scout",
    "research",
    "senior_staff_engineer",
    "architect",
    "coder",
    "qa",
    "reviewer",
    "publisher",
}

EXTERNAL_CURRENT_DOC_DOMAINS = (
    "external/current APIs, specs, CI syntax, package APIs, framework behavior, "
    "cloud APIs, Kubernetes specs, Docker Compose specs, Terraform providers, "
    "Ansible modules, GitHub Actions, GitLab CI, CLI flags, or language/library "
    "reference behavior"
)

LOCAL_DOCS_MCP_POLICY = f"""Local current-docs MCP policy for searxNcrawl/local-docs:
- Use the local-docs MCP server when a decision depends on {EXTERNAL_CURRENT_DOC_DOMAINS}.
- Prefer official/current primary documentation. Use targeted site: searches for known official docs domains when possible.
- Fast path: search first with at most 3 results, select one official/current URL, then crawl only that single page.
- Do not use crawl_site/site-wide crawling for normal implementation tasks unless the Team Lead explicitly asks for broad research.
- Do not repeat live lookups if an earlier role already cited a reliable official URL that covers the exact point.
- If local-docs/search/crawl is unavailable, say so explicitly and label any fallback guidance as non-verified model memory.
- Include the documentation URLs used in the role report/summary when external docs influenced the decision.
""".strip()


def local_docs_policy_context(role_title: str) -> str:
    title = (role_title or "").lower()
    if "team lead" in title or "orchestrator" in title:
        return f"""Current-docs routing policy:
- When the task materially depends on {EXTERNAL_CURRENT_DOC_DOMAINS}, normally route Research before implementation unless a prior role already provided authoritative current-docs evidence.
- In role instructions, ask the selected specialist to use the local-docs MCP server backed by searxNcrawl before making external syntax/API decisions.
- Keep docs lookup bounded: search first, crawl one official page, avoid crawl_site unless broad research is explicitly needed.
""".strip()
    if "scout" in title:
        return f"""Local current-docs routing hint:
- Scout is read-only and should not perform broad external research.
- If the task touches {EXTERNAL_CURRENT_DOC_DOMAINS}, set research_required=true and list concrete research_domains/research_questions for Research to verify with local-docs/searxNcrawl.
""".strip()
    if "senior staff" in title:
        return """Local current-docs strategy hint:
- If external/current API/spec/CI/config behavior affects correctness and Research did not provide authoritative current-docs evidence, return NEED_MORE_RESEARCH rather than allowing implementation from model memory.
- If current-docs evidence is present, turn it into target-runtime constraints and validation requirements.
""".strip()
    return LOCAL_DOCS_MCP_POLICY


def normalize_action(action: Any) -> str:
    if action is None:
        return ""
    return str(action).strip().upper().replace("-", "_").replace(" ", "_")


def _summary_dict(result: JsonDict | None) -> JsonDict:
    if not result:
        return {}
    summary = result.get("summary")
    return summary if isinstance(summary, dict) else {}


def _summary_value(result: JsonDict | None, key: str, default: Any = "") -> Any:
    if not result:
        return default
    summary = _summary_dict(result)
    if key in summary:
        return summary.get(key)
    aliases = {
        "status": "summary_status",
        "action": "summary_action",
        "risk_level": "risk_level",
        "blocking": "blocking",
    }
    alias = aliases.get(key)
    if alias and alias in result:
        return result.get(alias)
    return default


def _summary_text(result: JsonDict | None) -> str:
    return str(_summary_value(result, "summary", "") or "")


def _answer_text(result: JsonDict | None) -> str:
    return str((result or {}).get("answer") or "")


def _answer_len(result: JsonDict | None) -> int:
    return len(_answer_text(result))


def _short(value: Any, limit: int = 260) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text[: limit - 3] + "..." if len(text) > limit else text


def _role_result_meta_lines(result: JsonDict | None) -> list[str]:
    if not result:
        return ["- status: missing"]
    lines = [
        f"- report_id: {result.get('report_id') or 'unknown'}",
        f"- role: {result.get('role') or 'unknown'}",
        f"- role_instance: {result.get('role_instance') or 'unknown'}",
        f"- conversation_id: {result.get('conversation_id') or 'unknown'}",
        f"- ok: {result.get('ok')}",
        f"- status: {_summary_value(result, 'status', 'unknown') or 'unknown'}",
        f"- action: {_summary_value(result, 'action', 'unknown') or 'unknown'}",
        f"- risk_level: {_summary_value(result, 'risk_level', 'unknown') or 'unknown'}",
        f"- blocking: {_summary_value(result, 'blocking', False)}",
    ]
    if _summary_text(result):
        lines.append(f"- summary: {_summary_text(result)}")
    blocking_summary = _summary_value(result, "blocking_summary", [])
    if blocking_summary:
        lines.append(f"- blocking_summary: {blocking_summary}")
    role_report = result.get("role_report") if isinstance(result, dict) else None
    if isinstance(role_report, dict):
        compact = {k: role_report.get(k) for k in ("report_id", "role", "action", "summary", "risk_level", "blocking")}
        for key in (
            "research_required",
            "research_domains",
            "research_questions",
            "docs_lookup_used",
            "docs_sources",
            "files_changed",
            "ready_for_qa",
            "validation",
            "validation_review",
            "pr_checks",
        ):
            if role_report.get(key) not in (None, [], {}):
                compact[key] = role_report.get(key)
        lines.append(
            "- typed_report: "
            + json.dumps({k: v for k, v in compact.items() if v is not None}, ensure_ascii=False)[:1600]
        )
    return lines


def role_summary_context(state: JsonDict, role: str) -> str:
    result = state.get(f"{role}_result")
    if not result:
        return f"No {role} summary is available yet."
    return "\n".join(_role_result_meta_lines(result))


def role_answer_context(state: JsonDict, role: str, *, label: str | None = None) -> str:
    result = state.get(f"{role}_result")
    title = (label or role).upper()
    if not result:
        return f"No {role} answer is available yet."
    answer = _answer_text(result).strip()
    if not answer:
        return f"No full {role} answer was retained in graph state.\nUse the {role} summary/conversation_id as fallback."
    return f"----- BEGIN {title} ANSWER -----\n{answer}\n----- END {title} ANSWER -----"


def repository_context(state: JsonDict) -> str:
    repository = state.get("repository")
    if repository:
        return f"""Repository/workspace context:
- Requested repository, if OpenHands was configured to use one: {repository}
- Use the workspace/repository that OpenHands provides.
- Do not assume a fixed checkout directory.
- Do not create duplicate clones just because a hard-coded path is absent.
- If no repository is available but the task requires one, report a concrete blocker.""".strip()
    return """Repository/workspace context:
- No repository was specified in graph state.
- Use whatever workspace, repository, files, or environment OpenHands already provides.
- Do not assume or invent a repository path.
- If repository access is required but unavailable, report a concrete blocker instead of guessing.""".strip()


def shared_workspace_context() -> str:
    return """Shared workspace contract:
- Role conversations are separate, but they operate on the same mounted workspace/filesystem for this workflow.
- File changes made by writer roles are visible to later roles through the shared workspace.
- Docker sandbox images/runtime packages may differ between role conversations.
- Do not assume OS packages installed by another role are available in your container.
- Read-only roles must not modify shared workspace files.
- Writer/QA/reviewer/publisher roles must keep changes focused and report setup/install attempts.""".strip()


def latest_validation_profile(state: JsonDict) -> JsonDict:
    direct = state.get("validation_profile")
    if isinstance(direct, dict) and direct:
        return direct
    for result in reversed(list(state.get("role_results") or [])):
        if not isinstance(result, dict):
            continue
        report = result.get("role_report")
        if isinstance(report, dict) and isinstance(report.get("validation_profile"), dict) and report.get("validation_profile"):
            return report["validation_profile"]
        summary = result.get("summary")
        if isinstance(summary, dict) and isinstance(summary.get("validation_profile"), dict) and summary.get("validation_profile"):
            return summary["validation_profile"]
    return {}


def validation_profile_context(state: JsonDict) -> str:
    profile = latest_validation_profile(state)
    if not profile:
        return "Validation profile: not established yet.\nScout/Research/Senior Staff/Architect should discover required build/test/runtime targets when relevant."
    return "Validation profile / required target contract for this workflow:\n" + json.dumps(
        compact_validation_profile(profile), ensure_ascii=False, indent=2
    )


def _policy_context_from_team_lead(state: JsonDict) -> str:
    decision = state.get("team_lead_decision")
    if not isinstance(decision, dict):
        return "Latest Team Lead policy_evaluation: none."
    policy = decision.get("policy_evaluation")
    if not isinstance(policy, dict):
        return "Latest Team Lead policy_evaluation: none."
    important = {
        key: value
        for key, value in policy.items()
        if key
        in {
            "can_skip_qa",
            "skip_qa_reason",
            "can_skip_reviewer",
            "skip_reviewer_reason",
            "can_skip_research",
            "skip_research_reason",
            "can_skip_architect",
            "skip_architect_reason",
            "can_review",
            "can_publish",
            "qa_evidence_accepted",
            "reviewer_evidence_accepted",
            "publisher_pr_checks_accepted",
            "publisher_no_checks_accepted",
            "accepted_risks",
            "blocking_reasons",
        }
        and value not in (None, "", [], {})
    }
    if not important:
        return "Latest Team Lead policy_evaluation: no waivers/acceptance flags set."
    return "Latest Team Lead policy_evaluation:\n" + json.dumps(important, ensure_ascii=False, indent=2)


def team_lead_assignment_context(state: JsonDict) -> str:
    decision = state.get("team_lead_decision") or {}
    if not isinstance(decision, dict) or not decision:
        return "Team Lead assignment: none yet; follow your role contract."
    action = decision.get("action") or "RUN_ROLE"
    instructions = decision.get("instructions") or decision.get("reason") or ""
    context_sources = decision.get("context_sources") or []
    if not isinstance(context_sources, list):
        context_sources = [str(context_sources)]
    lines = [
        "Team Lead assignment for this role run:",
        f"- action: {action}",
        f"- requested_role: {decision.get('next_role') or decision.get('role') or 'unknown'}",
        f"- role_instance: {decision.get('role_instance') or 'auto'}",
    ]
    if instructions:
        lines.append(f"- instructions: {instructions}")
    if context_sources:
        lines.append(f"- requested_context_sources: {', '.join(map(str, context_sources))}")
    lines.append(_policy_context_from_team_lead(state))
    return "\n".join(lines)


def common_role_header(state: JsonDict, *, role_title: str) -> str:
    return f"""# Role: {role_title}

You are running inside an OpenHands sandbox as one specialist role in a larger LangGraph-controlled engineering workflow.

Original user task:
{state.get('user_task') or state.get('prompt') or ''}

{repository_context(state)}

{shared_workspace_context()}

Global workflow rules:
- Execute only the responsibility of your current role.
- LangGraph and Team Lead control role order. Do not launch, simulate, or claim later roles.
- Do not take over the whole workflow.
- Do not create pull requests unless your role explicitly says Publisher.
- Publishing boundary is absolute: every non-Publisher role MUST NOT create branches for publication, commit, push, create or update pull requests, call GitHub write APIs, run `gh pr create`, run `git push`, or use `GITHUB_TOKEN`.
- Be concrete and evidence-based: file paths, files inspected, commands inspected/run, observed results.
- If you cannot determine something, say exactly what is unknown and why.
- Avoid unrelated changes.

{local_docs_policy_context(role_title)}""".strip()


READ_ONLY_DISCOVERY_RULES = """Read-only discovery rules:
- You are read-only with respect to repository files, git state, branches, commits, dependencies, generated files, and environment.
- You may inspect files and run narrowly scoped read-only discovery commands.
- You MUST NOT run tests, builds, linters, formatters, generators, package installers, migrations, services, containers, or commands that may write files.
- You may document likely validation commands for later Coder/QA/Reviewer roles, but you must not execute them.
- If facts require running validation/build/test commands, report that limitation explicitly.""".strip()


MUTABLE_ENVIRONMENT_RULES = """Mutable sandbox/container environment rules:
- You are running inside an OpenHands Docker sandbox based on Debian Trixie.
- If an OS package is required and installing it is necessary and safe for your role, use sudo.
- Prefer minimal installation commands, for example: sudo apt-get update && sudo apt-get install -y .
- Do not use sudo for repository ownership hacks or broad unrelated system changes.
- Report every package installation attempt and why it was needed.
- Missing validation dependencies may be OS packages, language packages, generated sources, sibling checkouts, services, GUI/Xvfb, or documented directory layout requirements.""".strip()


def build_scout_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Scout / Read-Only Repository Investigator')}

{team_lead_assignment_context(state)}

{READ_ONLY_DISCOVERY_RULES}

Your responsibility: Collect factual context for Team Lead and later roles. Do not diagnose final causes.

Do:
- Inspect repository/workspace structure, relevant files, docs, CI/workflow metadata, package metadata, existing patterns, and user-provided logs.
- Extract exact failure evidence when available: failing job, step, command, error text, stack trace excerpt, failing test name, visible environment.
- Identify files/directories factually related to the task.
- List documented build/test/validation commands for later roles without executing them.
- Build a validation_profile only when the repository/task/CI/docs indicate real validation targets.
- Identify research domains only when external/runtime/tooling rules matter or are unknown.
- If the task touches current external APIs/specs/config/libraries, set research_required=true and list concrete domains/questions for Research.

Do not:
- Produce root-cause hypotheses, candidate causes, or diagnostic conclusions.
- Modify files, run tests/builds/installers, commit, push, or create PRs.

Output contract:
# Scout Context Report
## Task Understanding
## Factual Evidence
## Repository / Workspace Facts
## Relevant Files And Why
## Existing Patterns
## Documented Validation Commands To Run Later
## Validation Profile
## Research Routing Metadata
Include research_required, research_domains, research_questions, recommended_next_role.
## Role Routing Hints
State which later roles appear necessary and why, as factual hints only.
## Risks / Unknowns / Validation Questions

Final line: SCOUT_STATUS: COMPLETE""".strip()


def build_research_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Research / External Best-Practices Investigator')}

{team_lead_assignment_context(state)}

Scout report artifact:
{role_answer_context(state, 'scout', label='SCOUT REPORT')}

Scout routing/status summary:
{role_summary_context(state, 'scout')}

{validation_profile_context(state)}

Your responsibility: Research external best practices, official documentation, and target-runtime constraints for domains requested by Scout or Team Lead.

Boundaries:
- Research only. Do not modify files, run repo validation, push, or create PRs.
- Prefer official/current primary sources.
- Use local-docs MCP backed by searxNcrawl when external/current documentation matters.
- Search first with at most 3 results, choose one official/current page, then crawl only that single page.
- Do not use crawl_site/site-wide crawling unless the Team Lead explicitly asks for broad research.
- If internet/search/local-docs tools are unavailable, say so and clearly label stable general guidance as non-verified.

Output contract:
# Research Brief
## Inputs Reviewed
## Research Domains Covered
## Docs Lookup Evidence
For every docs lookup, include tool used, query, selected URL, source quality, and whether it was crawled.
## External Environment Contracts
## Cross-Environment Conflicts
## Validation Profile Additions Or Corrections
## Recommendations For Architect / Team Lead
## Research Gaps / Unknowns

Final line: RESEARCH_STATUS: COMPLETE""".strip()


def build_senior_staff_engineer_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Senior Staff Engineer / Execution Strategy Gate')}

{team_lead_assignment_context(state)}

{READ_ONLY_DISCOVERY_RULES}

Scout report artifact:
{role_answer_context(state, 'scout', label='SCOUT REPORT')}

Research brief artifact:
{role_answer_context(state, 'research', label='RESEARCH BRIEF')}

{validation_profile_context(state)}

Your responsibility: Turn the user task, Scout facts, and Research constraints into an execution contract and role-selection guidance.

Core policy:
- Do not force a fixed role chain. Recommend only roles that add necessary evidence or risk reduction for this task.
- If external/current API/spec/CI/config behavior affects correctness and Research did not provide authoritative current-docs evidence, return NEED_MORE_RESEARCH rather than allowing implementation from model memory.
- If current-docs evidence is present, turn it into target-runtime constraints and validation requirements.

Output contract:
# Senior Staff Engineering Strategy
## Decision
Exactly one ACTION: PROCEED, NEED_MORE_RESEARCH, NEED_MORE_SCOUT, ASK_HUMAN, or BLOCKER
## Problem Classification
## Target Runtime Contract
## Current-Docs Evidence Assessment
## Assumption Ledger
## Minimal Role Plan
## Cheap Preflight Checks
## Expensive Validation Strategy
## Risk Assessment
## Architect Constraints
## Coder Constraints
## QA Necessity Guidance
## Reviewer Necessity Guidance
## Publisher Constraints
## Stop Conditions

Final line: SENIOR_STAFF_STATUS: COMPLETE""".strip()


def build_architect_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Architect / Read-Only Implementation Planner')}

{team_lead_assignment_context(state)}

{READ_ONLY_DISCOVERY_RULES}

Scout report artifact:
{role_answer_context(state, 'scout', label='SCOUT REPORT')}

Research brief artifact:
{role_answer_context(state, 'research', label='RESEARCH BRIEF')}

Senior Staff strategy artifact:
{role_answer_context(state, 'senior_staff_engineer', label='SENIOR STAFF STRATEGY')}

{validation_profile_context(state)}

Your responsibility: Create a precise, minimal, testable implementation plan for Coder. Do not implement.

Role-flexibility guidance:
- Specify which validation is actually required by the task and target runtime.
- If full QA is likely unnecessary, explain the narrower evidence that would be sufficient and the residual risk.
- If the plan depends on external/current API/spec/config behavior and Research did not verify it with local-docs/searxNcrawl, request Research instead of planning from model memory.

Output contract:
# Architect Plan
## Goal
## Inputs Reviewed
## Environment / Target Runtime Contract
## Current-Docs Evidence Used
## Key Decisions
## Implementation Plan
## Files To Change
## Acceptance Criteria
## Validation Plan
## Minimal Required Role Evidence
## Risks And Mitigations
## Coder Instructions
## Do Not Do

Final line: ARCHITECT_STATUS: COMPLETE""".strip()


def build_coder_prompt(state: JsonDict) -> str:
    reviewer_feedback = state.get("reviewer_result") if state.get("current_iteration", 0) else None
    feedback_section = ""
    if reviewer_feedback:
        patched_state = {**state, "reviewer_result": reviewer_feedback}
        feedback_section = f"""
Reviewer feedback artifact from previous iteration:
{role_answer_context(patched_state, 'reviewer', label='REVIEWER FEEDBACK')}

Reviewer routing/status summary:
{role_summary_context(patched_state, 'reviewer')}
""".rstrip()
    return f"""{common_role_header(state, role_title='Coder / Implementer')}

{team_lead_assignment_context(state)}

{MUTABLE_ENVIRONMENT_RULES}

Senior Staff strategy artifact:
{role_answer_context(state, 'senior_staff_engineer', label='SENIOR STAFF STRATEGY')}

Architect plan artifact:
{role_answer_context(state, 'architect', label='ARCHITECT PLAN')}

{feedback_section}

Your responsibility: Implement the requested change with the smallest safe diff while obeying the accepted plan and Team Lead assignment.

Do:
- Use the available OpenHands workspace/repository context; do not assume a hard-coded checkout path.
- Keep changes focused on the original task.
- Before creating or changing external config formats or APIs such as GitHub Actions, GitLab CI, Docker Compose, Kubernetes YAML, Terraform, Ansible, pyproject.toml, package.json scripts, CLI flags, or framework/package APIs, use local-docs MCP/searxNcrawl unless Research already supplied an official URL covering the exact point.
- For docs lookup, search first with at most 3 results and crawl only one official/current page.
- Add/update tests when appropriate for the scope.
- Run the cheapest credible validation for your change: compile/build/test/lint/docs check as relevant.
- Report exactly what changed and what validation passed/failed/skipped.

Do not:
- Use crawl_site unless explicitly requested by Team Lead.
- Create branches for publication, commit, push, create/update PRs, use `GITHUB_TOKEN`, call GitHub write APIs, run `gh pr create`, run `git push`, hide failed validation, or claim readiness without evidence.

Output contract:
# Coder Report
## Summary
## Files Changed
## Docs Lookup Evidence
Include docs_lookup_used, source URLs, and gaps when external/current behavior influenced the implementation.
## Implementation Details
## Environment / Tool Installation
## Validation Environment Setup
## Build / Compile / Check Evidence
## Test / Smoke Evidence
## Acceptance Criteria Matrix
## Pipeline Readiness
One of: PIPELINE_READINESS: READY_FOR_REVIEW, NOT_READY_VALIDATION_FAILED, BLOCKED
## Known Issues
## Reviewer Notes

Final line: CODER_STATUS: COMPLETE""".strip()


def build_qa_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='QA / Validation Engineer')}

{team_lead_assignment_context(state)}

{MUTABLE_ENVIRONMENT_RULES}

Senior Staff strategy artifact:
{role_answer_context(state, 'senior_staff_engineer', label='SENIOR STAFF STRATEGY')}

Architect plan artifact:
{role_answer_context(state, 'architect', label='ARCHITECT PLAN')}

Coder routing/status summary:
{role_summary_context(state, 'coder')}

{validation_profile_context(state)}

Your responsibility: Validate that the implementation in the shared workspace actually works for the required target contract.

Validation policy:
- Inspect the actual repository/workspace state and current diff before testing.
- Map validation_profile.required_targets when present.
- Install reasonable missing validation tools with sudo when needed.
- Do not use live docs lookup by default; use it only if validation depends on current external syntax/CLI behavior not already covered by Research/Coder URLs.
- Do not skip runtime/smoke/integration/CI targets that are relevant to the task unless setup attempts produce a concrete blocker.

Output contract:
# QA Report
## Decision
ACTION: PASS, NEED_FIX, or BLOCKER
## Risk
RISK: LOW, MEDIUM, or HIGH
## Summary
## Repository / Diff Inspected
## Environment / Tool Installation
## Validation Environment Setup
## Build / Compile Evidence
## Test / Smoke / Integration Evidence
## Docs Lookup Evidence If Used
## Original Task Coverage
## Validation Evidence JSON
Include {{"validation": {{"build_ran": bool, "build_passed": bool, "tests_run": bool, "tests_passed": bool, "validation_level": "ci_like|targeted_runtime|targeted_integration|targeted_unit|syntax_only|not_applicable|not_validated", "targets": [], "gaps": [], "validation_gaps": [], "build_commands": [], "test_commands": [], "setup_commands": [], "install_commands": []}}}}
## Validation Gaps
## Required Fixes For Coder
## Reviewer Notes

Final line: QA_STATUS: COMPLETE""".strip()


def build_reviewer_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Reviewer / Independent Quality Gate')}

{team_lead_assignment_context(state)}

{MUTABLE_ENVIRONMENT_RULES}

Senior Staff strategy artifact:
{role_answer_context(state, 'senior_staff_engineer', label='SENIOR STAFF STRATEGY')}

Architect plan artifact:
{role_answer_context(state, 'architect', label='ARCHITECT PLAN')}

Coder routing/status summary:
{role_summary_context(state, 'coder')}

QA validation artifact, if Team Lead ran QA:
{role_answer_context(state, 'qa', label='QA VALIDATION REPORT')}

QA routing/status summary:
{role_summary_context(state, 'qa')}

{validation_profile_context(state)}

Your responsibility: Independently review the actual repository/workspace diff against the original task, accepted plan, available validation evidence, and Team Lead policy.

Flexible QA policy:
- QA evidence is valuable but not always mandatory. If Team Lead explicitly skipped QA with policy_evaluation.can_skip_qa=true, treat the waiver as an input, not as automatic acceptance.
- Inspect actual diff/files, not only summaries.
- When reviewing code/config that depends on external/current APIs or syntax, reuse Research/Coder cited official URLs first.
- Only call local-docs/searxNcrawl if the implementation uses syntax or behavior not supported by cited sources, or if you see suspicious external API/spec/config usage.
- Do not PASS if required runtime/smoke/integration/CI targets were skipped without concrete setup attempts.

Output contract:
# Reviewer Report
## Decision
ACTION: PASS, NEED_FIX, or BLOCKER
## Risk
RISK: LOW, MEDIUM, or HIGH
## Summary
## Evidence Reviewed
## Docs Verification Evidence
Include docs_verification_used, source URLs, and any unsupported external assumptions.
## QA Evidence / QA Waiver Review
## Independent Lint / Static Check Evidence
## Validation Review
## Acceptance Criteria Verification Matrix
## Findings
## Required Fixes For Coder
## Publisher Notes

Final line: REVIEWER_STATUS: COMPLETE""".strip()


def build_publisher_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Publisher / Delivery Publisher')}

{team_lead_assignment_context(state)}

{MUTABLE_ENVIRONMENT_RULES}

Senior Staff strategy artifact:
{role_answer_context(state, 'senior_staff_engineer', label='SENIOR STAFF STRATEGY')}

Architect plan artifact:
{role_answer_context(state, 'architect', label='ARCHITECT PLAN')}

QA routing/status summary:
{role_summary_context(state, 'qa')}

Reviewer routing/status summary:
{role_summary_context(state, 'reviewer')}

{validation_profile_context(state)}

Your responsibility depends on the accepted Team Lead work_order:
- repository/repo_change: inspect final repository changes, verify they match the task and accepted Team Lead policy, push a branch, create/find a GitHub PR using curl + GITHUB_TOKEN, then inspect PR checks with gh.
- external_publication/direct_external_api: perform only the bounded external publication requested by Team Lead, such as a GitHub Discussion/issue/release comment. Do not create helper scripts, commits, branches, pushes, or PRs unless Team Lead explicitly classifies the work_order as repository/repo_change.

Publishing rules:
- You are the only role allowed to push, create a PR, or perform bounded external write/publication actions.
- Use GITHUB_TOKEN from the environment. Never print or expose it.
- Create a PR with curl against GitHub REST API; do not use gh pr create for creation.
- Use gh for post-creation PR view/check/status operations.
- If checks exist, wait for them with gh pr checks --watch or an equivalent bounded gh polling loop and report final status.
- If no checks exist, do not invent CI success. Inspect whether the repo/branch actually has no check configuration/statuses, report structured pr_checks.overall_status="no_checks_configured" or "no_checks_found", waited=true, and include evidence.
- For external_publication, return structured `publication` evidence with published=true and artifact_url/url or artifact_id/comment_id/node_id.
- For repository publishing, return structured `publish` and `pr_checks` evidence.
- Do not modify implementation code. Return NEED_FIX/BLOCKER if code changes are required.
- Do not perform live docs lookup unless publishing behavior itself depends on current external API behavior not covered by prior roles.

Output contract:
# Publisher Report
## Decision
ACTION: PASS, NEED_FIX, or BLOCKER
## Published Branch
## Commit
## Pull Request
## External Publication
## PR Checks / Statuses
## Evidence Inspected
## Team Lead Policy / QA / Reviewer Constraint Check
## Commands Used
Do not include secrets.
## Risks / Notes

Final line: PUBLISHER_STATUS: COMPLETE""".strip()


def _team_lead_history_sections(state: JsonDict) -> str:
    results = [r for r in (state.get("role_results") or []) if isinstance(r, dict)]
    if not results:
        return "Specialist role results:\nNo specialist roles have completed or failed yet.\n\nPrevious Team Lead decisions:\nNo Team Lead decisions yet."
    specialist: list[str] = []
    failures: list[str] = []
    decisions: list[str] = []
    pending_or_absent: list[str] = []
    specialist_by_instance: set[str] = set()
    requested: list[tuple[str, str, str]] = []
    for result in results:
        role = str(result.get("role") or "unknown").lower()
        role_instance = str(result.get("role_instance") or role)
        action = normalize_action(result.get("summary_action") or _summary_value(result, "action", "unknown")) or "unknown"
        status = _summary_value(result, "status", result.get("status") or "unknown") or "unknown"
        risk = _summary_value(result, "risk_level", "unknown") or "unknown"
        blocking = _summary_value(result, "blocking", False)
        summary = _short(_summary_text(result), 500)
        conversation = result.get("conversation_id") or "unknown"
        report_id = result.get("report_id") or "unknown"
        if role == "team_lead":
            decision = result.get("summary") if isinstance(result.get("summary"), dict) else {}
            next_role = str((decision or {}).get("next_role") or "").strip().lower()
            next_instance = str((decision or {}).get("role_instance") or (f"{next_role}-1" if next_role else "")).strip()
            if action in TEAM_LEAD_RUN_ACTIONS and next_role:
                requested.append((next_role, next_instance, action))
            decisions.append(f"- {role_instance}: action={action} next_role={next_role or 'none'} role_instance={next_instance or 'none'}")
            if summary:
                decisions.append(f"  summary: {summary}")
            continue
        specialist_by_instance.add(role_instance)
        line = (
            f"- {role_instance} ({role}) report_id={report_id} status={status} action={action} "
            f"risk={risk} blocking={blocking} ok={result.get('ok')} conversation={conversation}"
        )
        target = failures if (result.get("ok") is False or status == "failed" or action in BLOCK_ACTIONS) else specialist
        target.append(line)
        if result.get("error"):
            target.append(f"  error: {_short(result.get('error'), 700)}")
        if summary:
            target.append(f"  summary: {summary}")
        role_report = result.get("role_report")
        if isinstance(role_report, dict):
            compact = {k: role_report.get(k) for k in ("report_id", "role", "action", "summary", "risk_level", "blocking")}
            for key in (
                "research_required",
                "research_domains",
                "files_changed",
                "docs_lookup_used",
                "docs_sources",
                "ready_for_qa",
                "validation",
                "validation_review",
                "pr_checks",
                "publication",
            ):
                if role_report.get(key) not in (None, [], {}):
                    compact[key] = role_report.get(key)
            target.append("  typed_report: " + _short(json.dumps({k: v for k, v in compact.items() if v is not None}, ensure_ascii=False), 1200))
    for next_role, next_instance, action in requested:
        if next_instance and next_instance not in specialist_by_instance:
            pending_or_absent.append(
                f"- {action} requested {next_instance} ({next_role}), but no specialist result for that role_instance is present. Do not assume it completed."
            )
    sections = ["Specialist role results:"]
    sections.extend(specialist or ["No successful specialist role results yet."])
    sections.append("\nFailed specialist role attempts:")
    sections.extend(failures or ["No failed specialist role attempts recorded."])
    sections.append("\nRequested roles without specialist result:")
    sections.extend(pending_or_absent or ["None."])
    sections.append("\nPrevious Team Lead decisions:")
    sections.extend(decisions or ["No Team Lead decisions yet."])
    return "\n".join(sections)


def build_team_lead_prompt(state: JsonDict) -> str:
    steps = int(state.get("team_lead_steps") or 0)
    max_steps = int(state.get("max_team_lead_steps") or 12)
    return f"""# Role: Team Lead / Orchestrator

You are the Team Lead for a LangGraph-controlled engineering workflow.

Original user task:
{state.get('user_task') or state.get('prompt') or ''}

{repository_context(state)}

{shared_workspace_context()}

{local_docs_policy_context('Team Lead / Orchestrator')}

Your responsibility: Decide the next specialist role to run, or stop the workflow. You are not an executor. You do not inspect files directly, write code, run tests, install packages, push branches, or create pull requests.

Current workflow step: {steps}/{max_steps}

Workflow history:
{_team_lead_history_sections(state)}

Allowed specialist roles / capability matrix:
- scout: read-only repository/workspace/log context discovery; facts only; no writes, tests, builds, installs, commits, pushes, or PRs.
- research: external best-practice / target-runtime research; uses local-docs/searxNcrawl when current docs matter; no repository writes, tests, builds, installs, commits, pushes, or PRs.
- senior_staff_engineer: execution contract, assumption ledger, strategy gate; no repository writes, tests, builds, installs, commits, pushes, or PRs.
- architect: read-only implementation plan; no repository writes, tests, builds, installs, commits, pushes, or PRs.
- coder: local implementation and relevant self-validation; may modify workspace files; must not create branches for publication, commit, push, create/update PRs, or use GitHub write credentials.
- qa: validation engineer; compile/build/run targeted checks when materially useful; no implementation, commits, pushes, or PRs.
- reviewer: independent review of actual diff, validation evidence or explicit QA waiver, and code quality; no implementation, commits, pushes, or PRs.
- publisher: the only role allowed to commit/push/publish, create/find GitHub PRs, post bounded external comments/announcements when assigned, and inspect/wait for PR checks/statuses.

Current-role assignment boundary:
- `instructions` must contain only work that the selected `next_role` is allowed to perform now.
- Do not put future workflow steps into `instructions`; put them only into `future_workflow_plan`.
- For every non-Publisher role, `instructions` must not ask for commit, branch creation for publication, push, PR / pull request creation or update, `gh pr`, GitHub write API calls, `GITHUB_TOKEN`, or any write-capable credential.
- If the selected role must use current docs, say so explicitly in `instructions` and request bounded local-docs/searxNcrawl use: search first, max 3 results, crawl one official/current page, no crawl_site unless broad research is needed.

Allowed actions:
- RUN_ROLE, RETRY_ROLE, STOP_COMPLETED, STOP_BLOCKED, ASK_HUMAN.

Work-order routing policy:
- First classify the task into work_order. This workflow is an IT work-order engine, not a fixed development ceremony.
- work_order.change_surface must describe what will change: none, repository, external_publication, live_server, kubernetes_cluster, monitoring, database, network, security, or unknown.
- work_order.execution_strategy must describe how work is delivered: answer_only, repo_change, direct_external_api, direct_live_execution, iac_or_gitops, investigation_only, or unknown.
- Choose the smallest safe role that can produce the next missing required_evidence item. A role may be selected only if it produces material evidence or performs an allowed mutation for this work_order.
- Do not select roles for ceremony. Do not choose Coder unless repository files must be changed. Do not choose QA/Reviewer unless there is a concrete implementation/configuration artifact, validation gap, or risk decision to validate/review.
- Prefer Scout first when repository/workspace/target facts are missing. Scout must collect facts/context only.
- Prefer Research when external/tool/runtime documentation is needed, Scout reports research_required/research_domains, or implementation/review would otherwise rely on model memory for current external syntax/API behavior.
- Prefer Senior Staff/Architect for uncertain, multi-file, public API, workflow, dependency, schema/proto, CI/runtime, deployment, security, or high-risk repository/live-infra changes.
- For repository changes: keep the strict engineering path. After Coder, decide whether QA is needed. Do not choose Publisher until you accepted either QA PASS or an explicit QA waiver, and either Reviewer PASS or an explicit Reviewer waiver. Coder changes files, QA validates or is explicitly waived, Reviewer reviews or is explicitly waived, Publisher creates/fetches PR evidence, and STOP_COMPLETED requires publisher_pr_checks_accepted=true plus PR/check evidence.
- For external_publication/direct_external_api tasks such as GitHub Discussion comments, issue comments, release announcements, or status updates: do not route to Coder merely to create a helper script; route to Publisher directly after Scout/Research evidence is sufficient. Publisher must return structured publication evidence, not PR checks.
- For live_server/kubernetes_cluster/monitoring/database/network/security work: use the existing roles as capabilities for now. Require target verification, readonly discovery, explicit plan, rollback path for risky mutation, execution evidence, and independent validation evidence when available. If the safe role does not exist yet, ASK_HUMAN instead of forcing Coder.
- Publisher PASS for repository changes is acceptable only with structured PR/check evidence. If checks exist, they must be successful. If no checks are configured/found, Publisher must report structured no-checks evidence; you may accept it by setting publisher_no_checks_accepted=true and publisher_pr_checks_accepted=true.
- Publisher PASS for external_publication is acceptable only with structured publication evidence: publication.published=true and artifact_url/url or artifact_id/comment_id/node_id. Accept it by setting publisher_publication_evidence_accepted=true.
- STOP_COMPLETED requires the evidence contract for the current work_order, not a fixed role chain.
- If the last specialist role failed before producing a usable result, retry that same role_instance when retryable, or ASK_HUMAN/STOP_BLOCKED when unsafe.
- If max steps is reached or the next safe role is unclear, choose ASK_HUMAN.

Policy evaluation guidance:
- Always include work_order and keep it consistent across decisions unless new evidence requires a change.
- Use accepted_report_ids for every report you rely on.
- For every skipped role, set the matching can_skip_* flag and reason.
- Put rejected/accepted gaps in blocking_reasons and accepted_risks.
- Do not claim a role completed just because you requested it earlier.

Decision output requirements:
When choosing RUN_ROLE/RETRY_ROLE, include work_order, capabilities_required, next_role, role_instance, context_sources, instructions, future_workflow_plan, assignment_scope_check, and reason.
Recommended role_instance names: scout-1, research-1, senior_staff_engineer-1, architect-1, coder-1, qa-1, reviewer-1, publisher-1.

Final line: TEAM_LEAD_STATUS: COMPLETE""".strip()


def build_team_lead_decision_prompt(state: JsonDict) -> str:
    base = build_team_lead_prompt(state)
    return f"""{base}

Direct decision mode:
- You are not running inside OpenHands.
- You have no tools, no filesystem, no shell, no browser, no task tracker.
- Do not claim that you inspected files, fetched URLs, read logs, ran commands, or completed a specialist role.
- Decide only from the Workflow history shown above.
- If no specialist role results exist, normally choose RUN_ROLE scout unless the task is pure external research.
- If choosing scout, instructions must say facts/context only and must not ask for hypotheses or candidate root causes.

Return exactly one compact valid JSON object. No Markdown. No prose.

Required JSON keys:
- valid: true
- status: "completed"
- summary: concise decision summary
- action: RUN_ROLE | RETRY_ROLE | STOP_COMPLETED | STOP_BLOCKED | ASK_HUMAN
- risk_level: low | medium | high | critical | null
- blocking: boolean
- blocking_summary: array of strings
- next_role: scout | research | senior_staff_engineer | architect | coder | qa | reviewer | publisher | null
- role_instance: recommended role instance or null
- work_order: object with keys intent, target_system, change_surface, artifact_kind, execution_strategy, risk_level, requires_human_approval, requires_rollback_plan, requires_validation, required_evidence, completed_evidence, forbidden_roles, preferred_roles
- capabilities_required: array of typed capabilities required from next_role, or []
- context_sources: array of state/artifact names to pass
- instructions: concise instructions for the selected specialist role only; no future-role work
- future_workflow_plan: array of future workflow steps that must not be executed by the selected specialist role
- assignment_scope_check: object with keys selected_role, instructions_contain_only_selected_role_work, future_work_not_instructions, publishing_actions_in_non_publisher_assignment, notes
- reason: why this is the next safe step
- accepted_report_ids: object with optional keys scout, research, senior_staff_engineer, architect, coder, qa, reviewer, publisher
- policy_evaluation: object with keys can_review, can_publish, can_complete, qa_evidence_accepted, reviewer_evidence_accepted, publisher_pr_checks_accepted, publisher_no_checks_accepted, publisher_publication_evidence_accepted, external_publication_accepted, publication_target_verified, publication_content_reviewed, no_repo_changes_accepted, target_verified, content_prepared, can_skip_discovery, skip_discovery_reason, validation_profile_accepted, pr_feedback_accepted, corrective_loop_required, can_skip_research, skip_research_reason, can_skip_architect, skip_architect_reason, can_skip_qa, skip_qa_reason, can_skip_reviewer, skip_reviewer_reason, scout_research_needed_accepted, senior_staff_strategy_accepted, implementation_scope_accepted, blocking_reasons, accepted_risks

For RUN_ROLE/RETRY_ROLE, invalid examples:
- next_role=coder with instructions containing commit/push/create PR. Put those items in future_workflow_plan and run publisher later instead.
- next_role=qa/reviewer with implementation or publishing tasks in instructions.
- next_role=scout with implementation, root-cause hypotheses, tests, builds, or patch requests.
- work_order.change_surface=external_publication with next_role=coder/qa/reviewer when no repository files need to change.""".strip()


def role_report_footer(role: str) -> str:
    role = (role or "role").lower()
    examples: dict[str, str] = {
        "scout": '{"schema_version":"1.0","role":"scout","action":"PASS","summary":"facts-only context collected","risk_level":"medium","blocking":false,"blocking_summary":[],"research_required":false,"research_domains":[],"research_questions":[],"validation_profile":{"profile_id":"validation-profile-1","required_targets":[]},"routing_hints":{"recommended_next_role":"architect","roles_likely_needed":[]},"facts":{"relevant_files":[],"documented_commands":[],"unknowns":[],"validation_questions":[]}}',
        "research": '{"schema_version":"1.0","role":"research","action":"PASS","summary":"research completed","risk_level":"medium","blocking":false,"blocking_summary":[],"domains":[],"findings":[],"docs_lookup_used":true,"docs_sources":[],"docs_lookup_gaps":[],"current_docs_confidence":"high|medium|low|not_available","validation_profile":{"profile_id":"validation-profile-1","required_targets":[]}}',
        "senior_staff_engineer": '{"schema_version":"1.0","role":"senior_staff_engineer","action":"PASS","summary":"strategy completed","risk_level":"medium","blocking":false,"blocking_summary":[],"fix_scope":"","files_to_change":[],"validation_strategy":"","architect_waiver_candidate":false,"routing_hints":{"roles_required":{"architect":true,"qa":true,"reviewer":true},"reason":""}}',
        "architect": '{"schema_version":"1.0","role":"architect","action":"PASS","summary":"plan ready","risk_level":"medium","blocking":false,"blocking_summary":[],"docs_sources_used":[],"plan":{"files_to_change":[],"acceptance_criteria":[],"validation_plan":[]},"validation_profile":{"profile_id":"validation-profile-1","required_targets":[]}}',
        "coder": '{"schema_version":"1.0","role":"coder","action":"PASS","summary":"implementation completed","risk_level":"medium","blocking":false,"blocking_summary":[],"change_set_id":"coder-1-attempt-1","files_changed":[],"docs_lookup_used":false,"docs_sources":[],"self_validation":{"build_commands":[],"test_commands":[],"passed":false,"gaps":[]},"ready_for_qa":true}',
        "qa": '{"schema_version":"1.0","role":"qa","action":"PASS","summary":"validation completed","risk_level":"low","blocking":false,"blocking_summary":[],"validated_change_set_id":"coder-1-attempt-1","docs_lookup_used":false,"docs_sources":[],"validation":{"overall_status":"passed","validation_level":"targeted_unit","targets":[],"gaps":[],"build_ran":true,"build_passed":true,"tests_run":true,"tests_passed":true,"build_commands":[],"test_commands":[],"setup_commands":[],"install_commands":[]},"required_targets_passed":true,"blocking_gaps":[],"accepted_gaps":[],"ready_for_review":true}',
        "reviewer": '{"schema_version":"1.0","role":"reviewer","action":"PASS","summary":"review passed","risk_level":"medium","blocking":false,"blocking_summary":[],"reviewed_change_set_id":"coder-1-attempt-1","docs_verification_used":false,"docs_sources":[],"review":{"diff_reviewed":true,"qa_evidence_reviewed":true,"qa_waiver_reviewed":false,"qa_evidence_accepted":true,"findings":[],"required_fixes":[],"publisher_ready":true},"validation_review":{"qa_build_evidence_ok":true,"qa_test_evidence_ok":true,"qa_validation_level_ok":true,"qa_skip_accepted":false,"lint_commands":[],"validation_gaps":[]}}',
        "publisher": '{"schema_version":"1.0","role":"publisher","action":"PASS","summary":"PR created and checks handled","risk_level":"low","blocking":false,"blocking_summary":[],"publish":{"branch":"feature/example","commit":"","head_sha":"","base":"main","pr_number":0,"pr_url":"","pushed":true,"pr_created":true},"pr_checks":{"overall_status":"passed","head_sha":"","waited":true,"check_runs":[],"commit_status":{"state":"success","statuses":[]},"failing_checks":[],"pending_checks":[],"checked_at":""},"publisher_recommendation":{"ready_to_complete":true,"reason":""}}',
    }
    example = examples.get(
        role,
        f'{{"schema_version":"1.0","role":"{role}","action":"PASS","summary":"","risk_level":"medium","blocking":false,"blocking_summary":[]}}',
    )
    return f"""Structured report requirement:
At the end of your answer, include exactly one machine-readable footer named FINAL_ROLE_REPORT_JSON.
This footer is used by Team Lead for policy decisions. The JSON must be valid, compact, and reflect what you actually did.
Common required keys: schema_version, role, action, summary, risk_level, blocking, blocking_summary.
Example shape:
FINAL_ROLE_REPORT_JSON: {example}""".strip()


def with_role_report_footer(role: str, prompt: str) -> str:
    if (role or "").lower() == "team_lead":
        return prompt
    return (prompt.rstrip() + "\n\n" + role_report_footer(role)).strip()


def build_role_prompt(role: str, state: JsonDict) -> str:
    role = (role or "role").lower()
    if role == "team_lead":
        return build_team_lead_prompt(state)
    if role == "scout":
        return with_role_report_footer(role, build_scout_prompt(state))
    if role == "research":
        return with_role_report_footer(role, build_research_prompt(state))
    if role == "senior_staff_engineer":
        return with_role_report_footer(role, build_senior_staff_engineer_prompt(state))
    if role == "architect":
        return with_role_report_footer(role, build_architect_prompt(state))
    if role == "coder":
        return with_role_report_footer(role, build_coder_prompt(state))
    if role == "qa":
        return with_role_report_footer(role, build_qa_prompt(state))
    if role == "reviewer":
        return with_role_report_footer(role, build_reviewer_prompt(state))
    if role == "publisher":
        return with_role_report_footer(role, build_publisher_prompt(state))
    return state.get("prompt") or state.get("user_task") or ""


def _summary_schema_contract(role: str, guidance: str) -> str:
    return f"""Return ONE compact valid JSON object only.
No Markdown, no code fence, no prose before/after JSON.
Required keys: valid, status, summary, action, risk_level, blocking, blocking_summary.
Allowed risk_level values: low, medium, high, critical, null.
The summary string must be concise, preferably under 900 characters.
Escape all quotes correctly.
Set blocking=true only for real blockers and put blocker details in blocking_summary.
{guidance}
Example shape: {{"valid": true, "status": "completed", "summary": "...", "action": "PASS", "risk_level": "low", "blocking": false, "blocking_summary": []}}"""


def build_role_summary_instructions(role: str) -> str:
    role = (role or "role").lower()
    if role == "team_lead":
        return _summary_schema_contract(
            role,
            "Team Lead action must be RUN_ROLE, RETRY_ROLE, STOP_COMPLETED, STOP_BLOCKED, or ASK_HUMAN. Include extra JSON keys: next_role, role_instance, context_sources, instructions, future_workflow_plan, assignment_scope_check, reason, accepted_report_ids, policy_evaluation. next_role must be one of the allowed roles for RUN_ROLE/RETRY_ROLE; otherwise null. instructions must contain only current selected-role work; future role steps go into future_workflow_plan. Do not execute work yourself.",
        )
    if role == "qa":
        return _summary_schema_contract(
            role,
            "QA action must be PASS only when required validation actually passed, or when validation is genuinely not applicable to a low-risk non-code/non-runtime task and this is explicitly justified. Include extra key validation with build_ran, build_passed, tests_run, tests_passed, validation_level, install_commands, setup_commands, build_commands, test_commands, targets, gaps, and validation_gaps. Include docs_lookup_used and docs_sources only when validation depended on current external documentation. Copy the validation object from the QA answer into this summary JSON; do not omit it.",
        )
    if role == "reviewer":
        return _summary_schema_contract(
            role,
            "Reviewer action must be PASS, NEED_FIX, or BLOCKER. PASS requires independent diff review and relevant lightweight checks. If QA was skipped by Team Lead, include validation_review.qa_skip_accepted=true with a concrete reason and evidence; otherwise include QA evidence review fields. Include docs_verification_used and docs_sources when review accepted or rejected external/current API/spec/config behavior. Include extra key validation_review and copy it from the reviewer answer.",
        )
    if role == "publisher":
        return _summary_schema_contract(
            role,
            "Publisher action must be PASS only when the assigned delivery work is complete with structured evidence. For repository publishing: a PR was created/found, pushed branch/head SHA identified, and PR checks/statuses were handled with gh. If checks exist, they must pass. If no checks are configured/found, include pr_checks.overall_status='no_checks_configured' or 'no_checks_found', waited=true, head_sha, and evidence fields; Team Lead decides whether to accept. For external publication: include publication.published=true and artifact_url/url or artifact_id/comment_id/node_id. Include extra keys pr_checks and/or publication and copy them from the publisher answer.",
        )
    if role == "coder":
        return _summary_schema_contract(
            role,
            "Use PASS only if implementation is ready for the next selected gate with relevant self-validation evidence or a concrete statement that no meaningful validation exists. Include files_changed, install commands, validation gaps, remaining known issues, docs_lookup_used, and docs_sources when implementation depended on external/current APIs, specs, CI syntax, config formats, CLI flags, or package/framework behavior.",
        )
    if role == "senior_staff_engineer":
        return _summary_schema_contract(
            role,
            "Senior Staff action must be PASS/PROCEED when the execution contract is ready, NEED_FIX/NEED_MORE_RESEARCH/NEED_MORE_SCOUT/ASK_HUMAN when more input is required, or BLOCKER when proceeding is unsafe. Include routing_hints for which roles are required/optional/unnecessary and why.",
        )
    if role == "architect":
        return _summary_schema_contract(
            role,
            "Use PASS if the implementation plan is ready for coder. Include key files, acceptance criteria, validation plan, minimal required role evidence, and docs_sources_used when relevant. Do not claim tests/builds were executed.",
        )
    if role == "research":
        return _summary_schema_contract(
            role,
            "Use PASS if the research brief is sufficient, NEED_FIX if Scout must provide clearer domains, or BLOCKER if required external research is impossible. Include covered domains, target-runtime constraints, portability risks, validation implications, docs_sources, docs_lookup_used, docs_lookup_gaps, and current_docs_confidence when local-docs/searxNcrawl was used or unavailable.",
        )
    if role == "scout":
        return _summary_schema_contract(
            role,
            "Use PASS if the facts-only context report is sufficient for routing, NEED_FIX if more read-only context is needed, or BLOCKER if repository/workspace/log access is unavailable. Include research_required, research_domains, research_questions, validation_profile, and routing_hints. Do not include root-cause hypotheses or claim tests/builds were executed.",
        )
    return _summary_schema_contract(role, "Use PASS, NEED_FIX, or BLOCKER according to the role result.")


def role_input_summary(role: str, state: JsonDict) -> list[str]:
    role = (role or "role").lower()
    lines: list[str] = []
    task = state.get("user_task") or state.get("prompt") or ""
    if task:
        lines.append(f"task: {_short(task, 160)}")
    lines.append(f"repository: {state.get('repository') or 'not specified; using OpenHands-provided workspace if any'}")
    if role == "team_lead":
        lines.append(f"recorded workflow events: {len(state.get('role_results') or [])}")
        lines.append(f"step: {int(state.get('team_lead_steps') or 0)}/{int(state.get('max_team_lead_steps') or 12)}")
        lines.append("mode: orchestration only; flexible role selection; returns JSON decision")
        lines.append("docs policy: route current external docs through Research/local-docs when needed")
    elif role == "scout":
        lines.append("mode: read-only facts/context discovery; tests/builds/installers forbidden")
    elif role == "research":
        scout = state.get("scout_result")
        lines.append(f"scout answer artifact: {_answer_len(scout)} chars")
        if _summary_text(scout):
            lines.append(f"scout routing summary: {_short(_summary_text(scout), 220)}")
        lines.append("mode: external best-practice research; use local-docs/searxNcrawl for current docs; repo changes/tests/builds/installers forbidden")
    elif role == "senior_staff_engineer":
        lines.append(f"scout artifact: {_answer_len(state.get('scout_result'))} chars")
        lines.append(f"research artifact: {_answer_len(state.get('research_result'))} chars")
        lines.append("mode: strategy gate; role necessity guidance; no commands/installers")
    elif role == "architect":
        lines.append(f"scout artifact: {_answer_len(state.get('scout_result'))} chars")
        lines.append(f"research artifact: {_answer_len(state.get('research_result'))} chars")
        lines.append(f"senior staff artifact: {_answer_len(state.get('senior_staff_engineer_result'))} chars")
        lines.append("mode: read-only planning; tests/builds/installers forbidden")
    elif role == "coder":
        lines.append(f"architect plan artifact: {_answer_len(state.get('architect_result'))} chars")
        lines.append(f"iteration: {int(state.get('current_iteration') or 0) + 1}")
        lines.append("mode: implementation/self-validation; use local-docs/searxNcrawl before external syntax/API decisions")
    elif role == "qa":
        lines.append(f"coder summary: {_short(_summary_text(state.get('coder_result')), 220)}")
        lines.append("mode: validation; can report not_applicable only for genuine low-risk non-runtime tasks")
    elif role == "reviewer":
        lines.append(f"coder summary: {_short(_summary_text(state.get('coder_result')), 220)}")
        lines.append(f"qa artifact: {_answer_len(state.get('qa_result'))} chars")
        lines.append("mode: independent review; verify suspicious external syntax/API behavior with local-docs when needed")
    elif role == "publisher":
        lines.append(f"qa summary: {_short(_summary_text(state.get('qa_result')), 220)}")
        lines.append(f"reviewer summary: {_short(_summary_text(state.get('reviewer_result')), 220)}")
        lines.append("mode: push branch, create/find PR, inspect/wait checks or structured no-checks evidence")
    else:
        lines.append("custom role prompt is passed as-is")
    return lines
