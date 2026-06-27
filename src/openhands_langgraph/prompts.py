from __future__ import annotations

from typing import Any

from .reports import compact_report_summary, compact_validation_profile

JsonDict = dict[str, Any]

PASS_ACTIONS = {"PASS", "COMPLETED", "DONE", "OK", "CONTINUE", "PLAN_READY"}
NEED_FIX_ACTIONS = {"NEED_FIX", "FIX", "REWORK", "RETRY"}
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


def _summary_dict(result: JsonDict | None) -> JsonDict:
    if not result:
        return {}
    summary = result.get("summary")
    if isinstance(summary, dict):
        return summary
    return {}


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
    value = _summary_value(result, "summary", "")
    return str(value or "")


def _answer_text(result: JsonDict | None) -> str:
    if not result:
        return ""
    return str(result.get("answer") or "")


def _answer_len(result: JsonDict | None) -> int:
    return len(_answer_text(result))


def _short(value: Any, limit: int = 260) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _role_result_meta_lines(result: JsonDict | None) -> list[str]:
    if not result:
        return ["- status: missing"]
    lines = [
        f"- role: {result.get('role') or 'unknown'}",
        f"- role_instance: {result.get('role_instance') or 'unknown'}",
        f"- conversation_id: {result.get('conversation_id') or 'unknown'}",
        f"- ok: {result.get('ok')}",
        f"- status: {_summary_value(result, 'status', 'unknown') or 'unknown'}",
        f"- action: {_summary_value(result, 'action', 'unknown') or 'unknown'}",
        f"- risk_level: {_summary_value(result, 'risk_level', 'unknown') or 'unknown'}",
        f"- blocking: {_summary_value(result, 'blocking', False)}",
    ]
    summary = _summary_text(result)
    if summary:
        lines.append(f"- summary: {summary}")
    blocking_summary = _summary_value(result, "blocking_summary", [])
    if blocking_summary:
        lines.append(f"- blocking_summary: {blocking_summary}")
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
        return f"No full {role} answer was retained in graph state. Use the {role} summary/conversation_id as a fallback."
    return f"""----- BEGIN {title} ANSWER -----
{answer}
----- END {title} ANSWER -----""".strip()


def repository_context(state: JsonDict) -> str:
    repository = state.get("repository")
    if repository:
        return f"""Repository/workspace context:
- Requested repository, if OpenHands was configured to use one: {repository}
- Use the workspace/repository that OpenHands provides.
- Do not assume a fixed checkout directory.
- Do not create duplicate clones just because a hard-coded path is absent.
- If no repository is available but the task requires one, report a concrete blocker.
""".strip()
    return """Repository/workspace context:
- No repository was specified in graph state.
- Use whatever workspace, repository, files, or environment OpenHands already provides.
- Do not assume or invent a repository path.
- If repository access is required but unavailable, report a concrete blocker instead of guessing.
""".strip()


def shared_workspace_context() -> str:
    return """Shared workspace contract:
- All role conversations operate on the same mounted workspace/filesystem for this workflow.
- Role conversations are separate, but repository file changes made by writer roles are visible to later roles through the shared workspace.
- Docker sandbox images/runtime packages may differ between role conversations. Do not assume OS packages installed by another role are available in your container.
- Read-only roles must not modify shared workspace files. Writer/QA/reviewer/publisher roles must keep changes focused and report any environment/package installation attempts.
""".strip()


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
        return "Validation profile: not established yet. Scout/Research/Senior Staff/Architect should discover required CI/runtime targets when relevant."
    import json

    compact = compact_validation_profile(profile)
    return "Validation profile / required target contract for this workflow:\n" + json.dumps(compact, ensure_ascii=False, indent=2)


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
- LangGraph validates and executes role order. Do not launch, simulate, or claim later roles.
- Do not take over the whole workflow.
- Do not create pull requests unless your role explicitly says publisher.
- Be concrete and evidence-based.
- Prefer explicit file paths, files inspected, commands inspected, and observed results.
- If you cannot determine something, say exactly what is unknown and why.
- Avoid unrelated changes.
""".strip()


READ_ONLY_DISCOVERY_RULES = """Read-only discovery rules for Scout/Research/Senior Staff/Architect:
- You are read-only with respect to repository files, git state, branches, commits, generated files, dependencies, and environment.
- You may inspect files and run narrowly scoped read-only discovery commands.
- You MUST NOT run tests, builds, linters, type checks, formatters, generators, installers, package managers, services, containers, migrations, or any command that may write files.
- You may discover and document likely validation commands for later Coder/QA/Reviewer roles, but you must not execute them.
""".strip()


MUTABLE_ENVIRONMENT_RULES = """Mutable sandbox/container environment rules for roles allowed to execute, validate, review, or publish:
- You are running inside an OpenHands Docker sandbox based on Debian Trixie.
- If an OS package is required and installing it is necessary and safe for your role, use sudo.
- Prefer minimal installation commands, for example: sudo apt-get update && sudo apt-get install -y <package>.
- Do not use sudo for repository file ownership hacks or broad system changes unrelated to the task.
- Report every package installation/setup attempt and why it was needed.
- Coder, QA, Reviewer, and Publisher must not skip required validation or publishing work only because a reasonable tool is missing; install missing reasonable tools when needed.
""".strip()


def build_scout_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Scout / Read-Only Repository Investigator')}

{team_lead_assignment_context(state)}

{READ_ONLY_DISCOVERY_RULES}

Your responsibility:
Investigate the available repository/workspace and task context. Produce a factual context report for later roles.

Strict facts-only rule:
- Do not produce root-cause hypotheses.
- Do not rank candidate causes.
- Do not write phrases such as "the root cause is", "likely root cause", "hypothesis", or "candidate root cause".

Do:
- Inspect repository structure, relevant files, build/test metadata, docs, CI logs when provided, and existing patterns.
- Extract exact factual failure context when the task references CI/logs.
- Identify relevant files and why they are relevant.
- List documented build/test/validation commands for later roles, without running them.
- Build an initial validation_profile from CI workflows, README, package scripts, Makefile/Gradle/npm/bundle/pytest commands, helper scripts, runtime services, required env vars, and original failing CI step.
- State whether external research is required before planning.

Output contract:
# Scout Context Report
## Task Understanding
## Factual CI / Log Evidence
## Repository / Workspace Facts
## Relevant Files And Why They Are Relevant
## Existing Patterns
## Documented Build/Test/Validation Commands To Run Later
## Validation Profile
## Research Routing Metadata
## Risks, Unknowns, And Missing Information
## Context Notes For Architect
## Context Notes For Coder
Final line: SCOUT_STATUS: COMPLETE
""".strip()


def build_research_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Research / External Best-Practices Investigator')}

{team_lead_assignment_context(state)}

Scout report artifact from previous role:
{role_answer_context(state, 'scout', label='SCOUT REPORT')}

Scout routing/status summary:
{role_summary_context(state, 'scout')}

{validation_profile_context(state)}

Your responsibility:
Research external best practices, official documentation, and target-runtime constraints for the domains requested by Scout. Do not modify files or run repository validation.

Output contract:
# Research Brief
## Inputs Reviewed
## Research Domains Covered
## External Environment Contracts
## Cross-Environment Conflicts To Resolve
## Validation Profile Additions Or Corrections
## Recommendations For Architect
## Research Gaps / Unknowns
Final line: RESEARCH_STATUS: COMPLETE
""".strip()


def build_senior_staff_engineer_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Senior Staff Engineer / Execution Strategy Gate')}

{team_lead_assignment_context(state)}

{READ_ONLY_DISCOVERY_RULES}

Scout report artifact from previous role:
{role_answer_context(state, 'scout', label='SCOUT REPORT')}

Research brief artifact from previous role:
{role_answer_context(state, 'research', label='RESEARCH BRIEF')}

{validation_profile_context(state)}

Your responsibility:
Turn the user task, Scout facts, and Research constraints into a senior-level engineering strategy and execution contract. Do not implement, edit files, run tests, install packages, push, or create PRs.

You must produce an Assumption Ledger:
- assumption
- target_environment
- confidence: high | medium | low
- evidence
- cheap_preflight_check
- expensive_validation
- failure_cost

Decision allowlist:
- ACTION: PROCEED
- ACTION: NEED_MORE_RESEARCH
- ACTION: NEED_MORE_SCOUT
- ACTION: ASK_HUMAN
- ACTION: BLOCKER

Output contract:
# Senior Staff Engineering Strategy
## Decision
## Problem Classification
## Target Runtime Contract
## Assumption Ledger
## Cheap Preflight Checks
## Expensive Validation Strategy
## Risk Assessment
## Architect Constraints
## Coder Constraints
## Reviewer Focus
## Publisher Constraints
## Stop Conditions
Final line: SENIOR_STAFF_STATUS: COMPLETE
""".strip()


def build_architect_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Architect / Read-Only Implementation Planner')}

{team_lead_assignment_context(state)}

{READ_ONLY_DISCOVERY_RULES}

Scout report artifact from previous role:
{role_answer_context(state, 'scout', label='SCOUT REPORT')}

Research brief artifact from previous role:
{role_answer_context(state, 'research', label='RESEARCH BRIEF')}

Senior Staff engineering strategy / execution contract artifact:
{role_answer_context(state, 'senior_staff_engineer', label='SENIOR STAFF STRATEGY')}

Your responsibility:
Create a precise implementation plan for the coder. Plan only. Do not implement, modify files, run tests, install packages, push, or create PRs.

Output contract:
# Architect Plan
## Goal
## Inputs Reviewed
## Research Brief Applied
## Senior Staff Strategy Applied
## Environment / Target Runtime Contract
## Assumption Ledger Applied
## Preflight Checks Required Before Expensive Actions
## Key Decisions
## Implementation Plan
## Files To Change
## Acceptance Criteria
## Validation Plan For Coder/QA/Reviewer
## Risks And Mitigations
## Coder Instructions
## Do Not Do
Final line: ARCHITECT_STATUS: COMPLETE
""".strip()


def build_coder_prompt(state: JsonDict) -> str:
    reviewer_feedback = state.get("reviewer_result") if state.get("current_iteration", 0) else None
    feedback_section = ""
    if reviewer_feedback:
        feedback_section = f"""
Reviewer feedback artifact from previous iteration:
{role_answer_context({**state, 'reviewer_result': reviewer_feedback}, 'reviewer', label='REVIEWER FEEDBACK')}

Reviewer routing/status summary:
{role_summary_context({**state, 'reviewer_result': reviewer_feedback}, 'reviewer')}
""".rstrip()
    return f"""{common_role_header(state, role_title='Coder / Implementer')}

{team_lead_assignment_context(state)}

Scout routing/status summary:
{role_summary_context(state, 'scout')}

Senior Staff engineering strategy / execution contract artifact:
{role_answer_context(state, 'senior_staff_engineer', label='SENIOR STAFF STRATEGY')}

{MUTABLE_ENVIRONMENT_RULES}

Architect implementation plan artifact:
{role_answer_context(state, 'architect', label='ARCHITECT PLAN')}

Architect routing/status summary:
{role_summary_context(state, 'architect')}
{feedback_section}

Your responsibility:
Implement the architect plan with the smallest safe code changes while obeying the Senior Staff execution contract, assumption ledger, and required preflight checks.

Hard safety rules:
- You may modify files only when required by the task and architect plan.
- Do not push and do not create pull requests.
- Do not modify unrelated files.
- If pre-existing uncommitted source/config/test changes are present, stop and report them unless clearly generated/cache artifacts.

Do:
- Keep changes focused.
- Add/update tests when appropriate.
- Compile/build the changed project or smallest affected module unless blocked.
- Run relevant targeted tests/smoke tests when feasible.
- Report exactly what changed and what validation passed/failed/skipped.

Output contract:
# Coder Report
## Summary
## Files Changed
## Implementation Details
## Environment / Tool Installation
## Validation Environment Setup
## Compilation / Build Evidence
## Test / Smoke Evidence
## Acceptance Criteria Implementation Matrix
## Execution Contract / Assumption Ledger Compliance
## Pipeline Readiness
Pipeline readiness must be one of:
PIPELINE_READINESS: READY_FOR_REVIEW
PIPELINE_READINESS: NOT_READY_VALIDATION_FAILED
PIPELINE_READINESS: BLOCKED
Final line: CODER_STATUS: COMPLETE
""".strip()


def build_qa_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='QA / Validation Engineer')}

{team_lead_assignment_context(state)}

Senior Staff engineering strategy / execution contract artifact:
{role_answer_context(state, 'senior_staff_engineer', label='SENIOR STAFF STRATEGY')}

{MUTABLE_ENVIRONMENT_RULES}

Architect implementation plan artifact:
{role_answer_context(state, 'architect', label='ARCHITECT PLAN')}

Coder routing/status summary, advisory only:
{role_summary_context(state, 'coder')}

{validation_profile_context(state)}

Your responsibility:
Validate that the implementation in the shared workspace actually builds and works.

Mandatory validation rules:
- Inspect actual repository/workspace state and current diff before testing.
- Map every validation_profile.required_targets target to validation.targets.
- Install reasonable missing tools and report every install command.
- Skipped tests are not passed tests.
- Syntax-level validation is not sufficient for runtime/CI/integration/smoke tasks.
- PASS requires credible build/test evidence or an explicit non-code/non-runtime task.

Output contract:
# QA Report
## Decision
Must contain exactly one line: ACTION: PASS, ACTION: NEED_FIX, or ACTION: BLOCKER
## Risk
Must contain exactly one line: RISK: LOW, RISK: MEDIUM, or RISK: HIGH
## Summary
## Repository / Diff Inspected
## Environment / Tool Installation
## Validation Environment Setup
## Compilation / Build Evidence
## Test / Smoke / Integration Evidence
## Original Failure Coverage
## Validation Evidence JSON
## Validation Gaps
## Required Fixes For Coder
## Reviewer Notes
Final line: QA_STATUS: COMPLETE
""".strip()


def build_reviewer_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Reviewer / Independent Quality Gate')}

{team_lead_assignment_context(state)}

Senior Staff engineering strategy / execution contract artifact:
{role_answer_context(state, 'senior_staff_engineer', label='SENIOR STAFF STRATEGY')}

{MUTABLE_ENVIRONMENT_RULES}

Architect implementation plan artifact:
{role_answer_context(state, 'architect', label='ARCHITECT PLAN')}

Coder routing/status summary, advisory only:
{role_summary_context(state, 'coder')}

QA validation report artifact:
{role_answer_context(state, 'qa', label='QA VALIDATION REPORT')}

QA routing/status summary:
{role_summary_context(state, 'qa')}

{validation_profile_context(state)}

Your responsibility:
Review the actual repository/workspace state independently against the original task, Senior Staff execution contract, architect plan, and QA validation evidence.

Review rules:
- You are read-only with respect to repository files, git history, branches, commits, and configuration.
- You may run safe read-only inspection and validation commands.
- Do not implement fixes, push branches, or create PRs.
- Do not accept QA PASS without credible build/test/runtime evidence for the task.

Output contract:
# Reviewer Report
## Decision
Must contain exactly one line: ACTION: PASS, ACTION: NEED_FIX, or ACTION: BLOCKER
## Risk
Must contain exactly one line: RISK: LOW, RISK: MEDIUM, or RISK: HIGH
## Summary
## Evidence Reviewed
## QA Evidence Review
## Independent Lint / Static Check Evidence
## Validation Environment Reconstruction Review
## QA Validation Evidence Gate
## Validation Review
## Execution Contract / Assumption Ledger Review
## Acceptance Criteria Verification Matrix
## Findings
## Required Fixes For Coder
## Publisher Notes
Final line: REVIEWER_STATUS: COMPLETE
""".strip()


def build_publisher_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Publisher / GitHub PR Publisher')}

{team_lead_assignment_context(state)}

Senior Staff engineering strategy / execution contract artifact:
{role_answer_context(state, 'senior_staff_engineer', label='SENIOR STAFF STRATEGY')}

Senior Staff routing/status summary:
{role_summary_context(state, 'senior_staff_engineer')}

{MUTABLE_ENVIRONMENT_RULES}

Architect implementation plan artifact:
{role_answer_context(state, 'architect', label='ARCHITECT PLAN')}

QA routing/status summary:
{role_summary_context(state, 'qa')}

Reviewer routing/status summary:
{role_summary_context(state, 'reviewer')}

{validation_profile_context(state)}

Your responsibility:
Inspect the final repository changes, verify they are safe against the Senior Staff execution contract, QA validation decision, and Reviewer decision, publish them to the remote GitHub repository, create a pull request using `curl` with `GITHUB_TOKEN`, then use the GitHub CLI (`gh`) authenticated with `GITHUB_TOKEN` for all post-creation PR inspection/check/status/watch operations, and return the check result to Team Lead. You are the only role allowed to push and create a PR.

Hard publishing rules:
- Use GITHUB_TOKEN from the environment. Never print or expose the token.
- Create the pull request with `curl` against the GitHub REST API using `GITHUB_TOKEN`. Do not use `gh pr create` for PR creation.
- Use the GitHub CLI (`gh`) for all actions after PR creation: PR discovery/view/list, head SHA inspection, PR checks, and waiting for checks.
- Raw GitHub REST API shell calls are allowed only for the PR creation step. Do not use raw REST/curl for check discovery/watch when `gh` can do it.
- If `gh` is missing, install it when reasonable. If installation is impossible, return ACTION: BLOCKER with exact evidence.
- Ensure `gh` is authenticated using GITHUB_TOKEN. Do not echo the token in logs.
- Push the prepared branch to the remote repository without leaking secrets.
- Do not modify implementation code. If code changes are required, return ACTION: NEED_FIX or ACTION: BLOCKER instead of editing.
- Do not publish unrelated, destructive, secret, generated-cache, or suspicious changes.
- If the repository is not a GitHub repository, GITHUB_TOKEN is missing, no relevant changes exist, PR creation via curl is impossible, `gh` cannot authenticate for post-creation inspection/checks, or remote/push is impossible, report ACTION: BLOCKER with exact evidence.

Required publishing procedure:
1. Inspect repository state: git status, current branch, remotes, diff/stat, recent commits.
2. Confirm the changes match the original task, Senior Staff constraints, architect plan, QA decision, and Reviewer decision.
3. Ensure `curl` is available for PR creation and `gh` is available for post-creation PR inspection/checks. Authenticate `gh` with `GITHUB_TOKEN` before PR inspection/check operations. Use `gh auth status` to verify authentication without exposing secrets.
4. Choose or create a safe feature branch when needed. Do not push directly to main/master unless the repository is already intentionally on a PR branch and that is safe.
5. Stage and commit only relevant changes if they are not already committed. Use a concise task-focused commit message.
6. Push the branch to the GitHub remote.
7. Create the PR with `curl` + `GITHUB_TOKEN` using the GitHub REST API `POST /repos/{{owner}}/{{repo}}/pulls`. The request body must include title, head, base, and body. The PR body must summarize changes, QA validation, reviewer decision, and risks. Do not use `gh pr create` for this step. If an open PR already exists for the branch, detect it with `gh pr view` / `gh pr list` and report it instead of creating a duplicate.
8. Capture and report: PR number, PR URL, branch/head ref, head SHA, base branch, and commit SHA. After PR creation via curl, use `gh pr view <number-or-branch> --json number,url,headRefName,headRefOid,baseRefName,state` to verify PR metadata.
9. After the PR exists, check which GitHub checks were triggered using `gh pr checks`. Use `gh pr checks <number> --json bucket,completedAt,description,event,link,name,startedAt,state,workflow` for machine-readable results.
10. Determine whether PR checks/statuses are actually configured for this repository before deciding how long to wait:
    - Inspect local `.github/workflows/` if present.
    - Run `gh workflow list` when available for this repository.
    - Run an initial `gh pr checks <number> --json bucket,completedAt,description,event,link,name,startedAt,state,workflow` read.
    - If no checks are visible immediately, wait a short no-checks grace window, then read `gh pr checks` again. Prefer `PUBLISHER_NO_CHECKS_GRACE_SECONDS` when present; otherwise use 120 seconds. This grace window is only for detecting whether checks exist, not for waiting for long-running checks.
11. If one or more check runs/status contexts exist, or GitHub Actions workflows/status checks are configured for the repository, wait until checks finish or a bounded timeout is reached. Prefer `gh pr checks <number> --watch --interval <seconds>` when suitable, plus a final JSON read with `gh pr checks <number> --json ...`. Prefer environment variables `PUBLISHER_CHECK_TIMEOUT_SECONDS` and `PUBLISHER_CHECK_POLL_SECONDS` when present; otherwise use a reasonable bounded wait such as 30 minutes timeout and 30 seconds poll interval.
12. If no workflows/status checks/check runs are configured or discovered after the no-checks grace window, do not treat that as a failed CI state. Return ACTION: PASS with structured `pr_checks.overall_status="no_checks_found"`, `pr_checks.checks_required=false`, `pr_checks.waited=true`, `pr_checks.no_checks_reason`, empty failing/pending checks, and evidence showing that the repository has no GitHub Actions workflows/status contexts for this PR.
13. Return the PR checks result to Team Lead in the structured publisher report. Team Lead decides whether to STOP_COMPLETED or continue corrective work. ACTION: PASS is allowed only when `pr_checks` is present, `waited=true`, `head_sha` is present, no failing or pending checks remain, and either `overall_status=passed/success` for configured checks or `overall_status=no_checks_found` with `checks_required=false` for repositories with no configured checks.

GitHub CLI requirements:
- Derive owner/repo from git remote or repository context when needed. Use `gh repo view --json nameWithOwner,defaultBranchRef` when useful.
- Use `GITHUB_TOKEN` for both curl PR creation and `gh` authentication; never print the token.
- Prefer base branch from repository default/main/master when discoverable.
- If a PR already exists for the branch, report the existing PR URL instead of creating duplicates when possible; use `gh pr view` / `gh pr list` for this discovery.
- Determine PR head SHA using `gh pr view <number-or-branch> --json headRefOid` when possible. If needed, use `git rev-parse HEAD` after pushing and verify it matches the PR head.
- Interpret `gh pr checks` JSON bucket/state values. Treat pass/skipping as non-failing unless project policy says otherwise; fail/cancel as failed; pending as not completed.
- `gh pr checks` may exit with a pending-checks exit code while checks are still running. Pending is not failure by itself; continue waiting until timeout or completion.
- If no checks appear after the no-checks grace window and repository evidence shows no GitHub Actions workflows/status contexts are configured, report `pr_checks.overall_status=no_checks_found`, `pr_checks.checks_required=false`, and return ACTION: PASS.
- If checks are expected because workflows/status contexts exist but no check result appears before timeout, return ACTION: NEED_FIX or BLOCKER with `pr_checks.overall_status=timed_out` or `no_checks_found`, `pr_checks.checks_required=true`, and exact evidence.
- If checks are pending at timeout, return ACTION: NEED_FIX with `pr_checks.overall_status=timed_out` or `pending` and include pending check names.
- If checks fail or are cancelled, return ACTION: NEED_FIX unless publishing itself failed in a way that is a BLOCKER. Include failing check names, states/buckets, URLs, workflows, and logs/URLs when available.
- If checks pass, return ACTION: PASS and include `pr_checks.overall_status=passed`.
- If no checks are configured, return ACTION: PASS and include `pr_checks.overall_status=no_checks_found`, `checks_required=false`, `waited=true`, `no_checks_reason`, and the gh/local evidence used to establish that no checks are configured.
- If you created/found a PR but did not run `gh pr checks --json ...` at least once after the no-checks grace window, do not return PASS. If checks exist, you must also run `gh pr checks --watch` or an equivalent bounded gh polling loop before PASS.

Output contract:
# Publisher Report
## Decision
Must contain exactly one line: ACTION: PASS, ACTION: NEED_FIX, or ACTION: BLOCKER
## Published Branch
## Commit
## Pull Request
## PR Checks / Statuses
List check runs/status contexts, their status/conclusion/state, URLs, and final overall outcome. If no checks are configured, include explicit no-checks evidence.
## Evidence Inspected
## Senior Staff / QA / Reviewer Constraint Check
## Commands Used
Include the sanitized curl command used to create the PR and the gh commands used for PR view/checks. Do not include secrets.
## Risks / Notes
Final line: PUBLISHER_STATUS: COMPLETE
""".strip()


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
        action = _summary_value(result, "action", "unknown") or "unknown"
        status = _summary_value(result, "status", result.get("status") or "unknown") or "unknown"
        risk = _summary_value(result, "risk_level", "unknown") or "unknown"
        blocking = _summary_value(result, "blocking", False)
        summary = _short(_summary_text(result), 500)
        conversation = result.get("conversation_id") or "unknown"

        if role == "team_lead":
            decision = result.get("summary") if isinstance(result.get("summary"), dict) else {}
            next_role = str((decision or {}).get("next_role") or (decision or {}).get("role") or "").strip().lower()
            next_instance = str((decision or {}).get("role_instance") or (f"{next_role}-1" if next_role else "")).strip()
            if action in TEAM_LEAD_RUN_ACTIONS and next_role:
                requested.append((next_role, next_instance, action))
            decisions.append(f"- {role_instance}: action={action} next_role={next_role or 'none'} role_instance={next_instance or 'none'}")
            if summary:
                decisions.append(f"  summary: {summary}")
            continue

        specialist_by_instance.add(role_instance)
        line = f"- {role_instance} ({role}) status={status} action={action} risk={risk} blocking={blocking} ok={result.get('ok')} conversation={conversation}"
        target = failures if (result.get("ok") is False or status == "failed" or action in BLOCK_ACTIONS) else specialist
        target.append(line)
        if result.get("error"):
            target.append(f"  error: {_short(result.get('error'), 700)}")
        if summary:
            target.append(f"  summary: {summary}")
        role_report = result.get("role_report") if isinstance(result.get("role_report"), dict) else None
        if role_report:
            target.append("  typed_report: " + _short(compact_report_summary(role_report), 1200))

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

Your responsibility:
Decide the next specialist role to run, or stop the workflow. You are not an executor. You do not inspect files directly, write code, run tests, install packages, push branches, or create pull requests.

Current workflow step: {steps}/{max_steps}

Workflow history:
{_team_lead_history_sections(state)}

Allowed specialist roles:
- scout: read-only repository/workspace/log context discovery; facts only, no root-cause hypotheses.
- research: external best-practice / target-runtime research.
- senior_staff_engineer: execution contract, assumption ledger, strategy gate.
- architect: read-only implementation plan.
- coder: modify files and validate implementation.
- qa: validation engineer; install tools, compile/build, and run targeted tests/smoke tests.
- reviewer: independent review of shared workspace/diff, QA evidence, and code quality.
- publisher: inspect final changes, push branch, create GitHub PR via curl + GITHUB_TOKEN, then use gh for PR inspection/checks/status waiting and report their result.

Allowed actions:
- RUN_ROLE
- RETRY_ROLE
- STOP_COMPLETED
- STOP_BLOCKED
- ASK_HUMAN

Delivery policy you must evaluate as Team Lead:
- A Team Lead RUN_ROLE decision only means a role was requested; it does NOT mean that role completed.
- Prefer scout before research when repository facts are missing.
- Prefer research when target runtime/external environment rules are important or unknown.
- Prefer senior_staff_engineer before architect when execution environment assumptions or high-level risks exist.
- Architect is normally required before coder unless you explicitly accept a low-risk senior staff waiver.
- After coder returns PASS/ready, normally choose RUN_ROLE qa before reviewer.
- After QA returns PASS, inspect QA typed report and decide whether gaps are blocking, accepted risk, or require retry.
- After reviewer returns PASS, inspect reviewer typed report and decide whether publishing is safe.
- Do not choose publisher until you explicitly accept both QA and reviewer evidence in policy_evaluation and set policy_evaluation.can_publish=true.
- After publisher returns, inspect publish.pr_url, publish.head_sha, and pr_checks.
- Publisher PASS is not acceptable without structured pr_checks evidence.
- Acceptable publisher pr_checks evidence is either:
  (a) gh discovered PR checks/statuses, waited for them, and they completed successfully; or
  (b) gh/local repository evidence shows no GitHub Actions workflows/status contexts/check runs are configured, Publisher waited a short no-checks grace window, and pr_checks has overall_status=no_checks_found, checks_required=false, waited=true, no failing/pending checks, and a concrete no_checks_reason.
- If publisher created a PR but did not report pr_checks, did not identify head_sha, did not run gh pr checks after a no-checks grace window, reported timed_out/pending/failing checks, reported no_checks_found with checks_required=true, or only summarized PR creation, choose RETRY_ROLE publisher with instructions to use gh pr view and gh pr checks --json/--watch as appropriate, not STOP_COMPLETED.
- If PR checks/statuses completed successfully, or if no checks are configured and Publisher provided acceptable no_checks_found evidence, choose STOP_COMPLETED with policy_evaluation.can_complete=true and publisher_pr_checks_accepted=true.
- If checks failed, cancelled, timed out, were expected but missing, or publisher returned NEED_FIX/BLOCKER, treat PR checks as a new feedback loop.
- For STOP_COMPLETED after publisher, set policy_evaluation.can_complete=true and publisher_pr_checks_accepted=true only if you accepted the publisher PR URL/head SHA and either the reported PR checks/statuses completed successfully or Publisher proved no checks/statuses are configured with pr_checks.overall_status=no_checks_found and checks_required=false. Do not complete on PR creation alone.

Decision output requirements:
Your normal answer must be concise and explain only the next decision. The summary JSON for this role must contain all routing fields listed in the summary instruction.
When choosing RUN_ROLE/RETRY_ROLE, include next_role, role_instance, context_sources, instructions, and reason.
Recommended role_instance names: scout-1, research-1, senior_staff_engineer-1, architect-1, coder-1, qa-1, reviewer-1, publisher-1.

Final line: TEAM_LEAD_STATUS: COMPLETE
""".strip()


def build_team_lead_decision_prompt(state: JsonDict) -> str:
    base = build_team_lead_prompt(state)
    return f"""{base}

Direct decision mode:
- You are not running inside OpenHands.
- You have no tools, no filesystem, no shell, no browser, no task tracker.
- Do not claim that you inspected files, fetched URLs, read logs, ran commands, or completed a specialist role.
- Decide only from the Workflow history shown above.
- If no specialist role results exist, normally choose RUN_ROLE scout unless the task is pure external research.
- If choosing scout, its instructions must say facts/context only and must not ask for hypotheses or candidate root causes.

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
- context_sources: array of state/artifact names to pass
- instructions: concise instructions for the selected specialist role
- reason: why this is the next safe step
- accepted_report_ids: object with optional keys scout, research, senior_staff_engineer, architect, coder, qa, reviewer, publisher
- policy_evaluation: object with keys can_review, can_publish, can_complete, qa_evidence_accepted, reviewer_evidence_accepted, publisher_pr_checks_accepted, validation_profile_accepted, pr_feedback_accepted, corrective_loop_required, can_skip_research, skip_research_reason, can_skip_architect, skip_architect_reason, scout_research_needed_accepted, senior_staff_strategy_accepted, implementation_scope_accepted, blocking_reasons, accepted_risks
""".strip()


def role_report_footer(role: str) -> str:
    role = (role or "role").lower()
    examples: dict[str, str] = {
        "publisher": '''FINAL_ROLE_REPORT_JSON: { "schema_version": "1.0", "role": "publisher", "action": "PASS", "summary": "PR created/found and no checks are configured", "risk_level": "low", "blocking": false, "blocking_summary": [], "publish": {"branch": "feature/example", "commit": "", "head_sha": "", "base": "main", "pr_number": 0, "pr_url": "", "pushed": true, "pr_created": true, "existing_pr": false}, "pr_checks": { "overall_status": "no_checks_found", "checks_required": false, "no_checks_reason": "No .github/workflows directory, gh workflow list returned no workflows, and gh pr checks returned no check runs after the grace wait.", "head_sha": "", "waited": true, "timeout_seconds": 120, "poll_interval_seconds": 30, "check_runs": [], "commit_status": {"state": "no_status", "statuses": []}, "failing_checks": [], "pending_checks": [], "checked_at": "" }, "publisher_recommendation": {"ready_to_complete": true, "recommended_next_role": "team_lead", "reason": "No checks are configured for this repository"} }''',
        "qa": '''FINAL_ROLE_REPORT_JSON: { "schema_version": "1.0", "role": "qa", "action": "PASS", "summary": "validation completed", "risk_level": "low", "blocking": false, "blocking_summary": [], "validation": { "overall_status": "passed", "validation_level": "targeted_integration", "build_ran": true, "build_passed": true, "tests_run": true, "tests_passed": true, "build_commands": [], "test_commands": [], "setup_commands": [], "install_commands": [], "targets": [], "gaps": [], "validation_gaps": [] }, "ready_for_review": true }''',
        "reviewer": '''FINAL_ROLE_REPORT_JSON: { "schema_version": "1.0", "role": "reviewer", "action": "PASS", "summary": "review passed", "risk_level": "medium", "blocking": false, "blocking_summary": [], "review": { "diff_reviewed": true, "qa_evidence_reviewed": true, "qa_evidence_accepted": true, "findings": [], "required_fixes": [], "publisher_ready": true }, "validation_review": { "qa_build_evidence_ok": true, "qa_test_evidence_ok": true, "qa_validation_level_ok": true, "environment_reconstruction_reviewed": true, "syntax_only_rejected": true, "lint_commands": [], "setup_commands_reviewed": [], "validation_gaps": [] } }''',
    }
    default = f'''FINAL_ROLE_REPORT_JSON: {{"schema_version": "1.0", "role": "{role}", "action": "PASS", "summary": "", "risk_level": "medium", "blocking": false, "blocking_summary": []}}'''
    example = examples.get(role, default)
    return f"""Structured report requirement:
At the end of your answer, include exactly one machine-readable footer named FINAL_ROLE_REPORT_JSON.
This footer is used by Team Lead for policy decisions. Do not rely on prose only. The JSON must be valid, compact enough to parse, and must reflect what you actually did.
Common required keys: schema_version, role, action, summary, risk_level, blocking, blocking_summary.
Example shape:
{example}
""".strip()


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
The summary string must be concise, preferably under 900 characters. Escape all quotes correctly.
Set blocking=true only for real blockers and put blocker details in blocking_summary.
{guidance}
Example shape: {{"valid": true, "status": "completed", "summary": "...", "action": "PASS", "risk_level": "low", "blocking": false, "blocking_summary": []}}
""".strip()


def build_role_summary_instructions(role: str) -> str:
    role = (role or "role").lower()
    if role == "team_lead":
        return _summary_schema_contract(
            role,
            "Team Lead action must be RUN_ROLE, RETRY_ROLE, STOP_COMPLETED, STOP_BLOCKED, or ASK_HUMAN. Include extra JSON keys: next_role, role_instance, context_sources, instructions, reason. next_role must be one of scout, research, senior_staff_engineer, architect, coder, qa, reviewer, publisher for RUN_ROLE/RETRY_ROLE; otherwise null. Do not execute work yourself.",
        )
    if role == "qa":
        return _summary_schema_contract(
            role,
            "QA action must be PASS only when compilation/build and targeted test/smoke/integration validation actually ran and passed in a credible validation environment. Include extra key validation with build_ran, build_passed, tests_run, tests_passed, validation_level, install_commands, setup_commands, build_commands, test_commands, targets, gaps, and validation_gaps. Copy the validation object from the QA answer into this summary JSON exactly; do not omit it.",
        )
    if role == "reviewer":
        return _summary_schema_contract(
            role,
            "Reviewer action must be PASS, NEED_FIX, or BLOCKER. PASS requires QA PASS with credible build/test validation evidence plus independent code/diff review. Include extra key validation_review. Copy the validation_review object from the reviewer answer into this summary JSON exactly; do not omit it.",
        )
    if role == "publisher":
        return _summary_schema_contract(
            role,
            "Publisher action must be PASS only when a PR was created/found, the pushed branch/head SHA was identified, and either GitHub PR checks/statuses were discovered with gh, waited for with gh pr checks --watch or an equivalent bounded gh polling loop, completed successfully, and publishing is ready for Team Lead to stop; or no checks/statuses are configured for the repository after a short no-checks grace wait. Use PASS in the no-checks case only when pr_checks has overall_status=no_checks_found, checks_required=false, waited=true, no failing/pending checks, and a concrete no_checks_reason/evidence. Use NEED_FIX when PR checks/statuses fail, are cancelled, remain pending at timeout, checks are expected but no checks are found at timeout, or checks indicate code/test changes are required. Use BLOCKER when publishing/check discovery cannot proceed because of GitHub/GITHUB_TOKEN/gh/push blockers. Include extra key pr_checks with overall_status, checks_required, no_checks_reason, head_sha, waited, timeout_seconds, poll_interval_seconds, check_runs, commit_status, failing_checks, pending_checks, and checked_at. Copy the pr_checks object from the publisher answer into summary JSON exactly; do not omit it. PASS is invalid without pr_checks; PASS with no_checks_found is invalid unless checks_required=false and no failing/pending checks remain.",
        )
    if role == "coder":
        return _summary_schema_contract(
            role,
            "Use PASS only if implementation is ready for QA with compilation/build and targeted validation evidence, NEED_FIX if validation failed due to the change, or BLOCKER if implementation could not proceed. Include install commands, compile/build/test status, validation gaps, and remaining known issues.",
        )
    if role == "senior_staff_engineer":
        return _summary_schema_contract(
            role,
            "Senior Staff action must be PASS/PROCEED when the execution contract is ready for Architect, NEED_FIX/NEED_MORE_RESEARCH/NEED_MORE_SCOUT/ASK_HUMAN when more input is required, or BLOCKER when proceeding is unsafe. Include structured fields when available: root_cause, fix_scope, files_to_change, files_inspected, validation_strategy, confidence, architect_waiver_candidate, routing_hints, target_runtime_contract, assumption_ledger.",
        )
    if role == "architect":
        return _summary_schema_contract(
            role,
            "Use PASS if the implementation plan is ready for coder, NEED_FIX if more scout/research information is required, or BLOCKER if planning is impossible. Include key files, environment/target-runtime contract, acceptance criteria, and validation plan. Do not claim that tests/builds were executed.",
        )
    if role == "research":
        return _summary_schema_contract(
            role,
            "Use PASS if the research brief is sufficient for architect, NEED_FIX if Scout must provide clearer domains, or BLOCKER if required external research is impossible. Include covered domains, target-runtime constraints, portability risks, and validation implications. Do not claim repository tests/builds were executed.",
        )
    if role == "scout":
        return _summary_schema_contract(
            role,
            "Use PASS if the facts-only scout context report is sufficient for routing, NEED_FIX if more read-only context discovery is needed, or BLOCKER if repository/workspace/log access is unavailable. Include structured research_required, research_domains, research_questions, factual failure evidence, relevant files, discovered validation commands, risks, unknowns, validation_questions, and routing_hints. Do not include root-cause hypotheses or claim that tests/builds were executed.",
        )
    return _summary_schema_contract(role, "Use PASS, NEED_FIX, or BLOCKER according to the role result.")


def normalize_action(action: Any) -> str:
    if action is None:
        return ""
    return str(action).strip().upper().replace("-", "_").replace(" ", "_")


def role_input_summary(role: str, state: JsonDict) -> list[str]:
    role = (role or "role").lower()
    lines: list[str] = []
    task = state.get("user_task") or state.get("prompt") or ""
    if task:
        short_task = str(task).replace("\n", " ")
        if len(short_task) > 160:
            short_task = short_task[:157] + "..."
        lines.append(f"task: {short_task}")
    if state.get("repository"):
        lines.append(f"repository: {state.get('repository')}")
    else:
        lines.append("repository: not specified; using OpenHands-provided workspace if any")

    if role == "team_lead":
        lines.append(f"recorded workflow events: {len(state.get('role_results') or [])}")
        lines.append(f"step: {int(state.get('team_lead_steps') or 0)}/{int(state.get('max_team_lead_steps') or 12)}")
        lines.append("mode: orchestration only; returns JSON decision; no commands/files/push")
    elif role == "scout":
        lines.append("upstream: none")
        lines.append("mode: read-only discovery; tests/builds/installers forbidden")
    elif role == "research":
        scout = state.get("scout_result")
        lines.append(f"scout answer artifact: {_answer_len(scout)} chars")
        if _summary_text(scout):
            lines.append(f"scout routing summary: {_short(_summary_text(scout), 220)}")
        lines.append("mode: external best-practice research; repo changes/tests/builds/installers forbidden")
    elif role == "senior_staff_engineer":
        scout = state.get("scout_result")
        research = state.get("research_result")
        lines.append(f"scout answer artifact: {_answer_len(scout)} chars")
        lines.append(f"research brief artifact: {_answer_len(research)} chars")
        lines.append("mode: senior strategy gate; execution contract + assumption ledger; no commands/installers")
    elif role == "architect":
        scout = state.get("scout_result")
        research = state.get("research_result")
        senior = state.get("senior_staff_engineer_result")
        lines.append(f"scout answer artifact: {_answer_len(scout)} chars")
        lines.append(f"research brief artifact: {_answer_len(research)} chars")
        lines.append(f"senior staff strategy artifact: {_answer_len(senior)} chars")
        lines.append("mode: read-only planning; tests/builds/installers forbidden")
    elif role == "coder":
        senior = state.get("senior_staff_engineer_result")
        architect = state.get("architect_result")
        lines.append(f"senior staff strategy artifact: {_answer_len(senior)} chars")
        lines.append(f"architect plan artifact: {_answer_len(architect)} chars")
        lines.append(f"iteration: {int(state.get('current_iteration') or 0) + 1}")
        lines.append("mode: implementation/validation in Debian Trixie Docker sandbox; install packages with sudo when needed")
    elif role == "qa":
        senior = state.get("senior_staff_engineer_result")
        architect = state.get("architect_result")
        coder = state.get("coder_result")
        lines.append(f"senior staff strategy artifact: {_answer_len(senior)} chars")
        lines.append(f"architect plan artifact: {_answer_len(architect)} chars")
        if _summary_text(coder):
            lines.append(f"coder routing summary only: {_short(_summary_text(coder), 220)}")
        lines.append("mode: QA validation; install required utilities with sudo; compile/build and run targeted tests")
    elif role == "reviewer":
        senior = state.get("senior_staff_engineer_result")
        architect = state.get("architect_result")
        qa = state.get("qa_result")
        lines.append(f"senior staff strategy artifact: {_answer_len(senior)} chars")
        lines.append(f"architect plan artifact: {_answer_len(architect)} chars")
        lines.append(f"qa validation artifact: {_answer_len(qa)} chars")
        lines.append("mode: independent review after QA; install required linters/checkers with sudo; do not modify implementation files")
    elif role == "publisher":
        senior = state.get("senior_staff_engineer_result")
        architect = state.get("architect_result")
        reviewer = state.get("reviewer_result")
        qa = state.get("qa_result")
        lines.append(f"senior staff strategy artifact: {_answer_len(senior)} chars")
        lines.append(f"architect plan artifact: {_answer_len(architect)} chars")
        if _summary_text(qa):
            lines.append(f"qa routing summary: {_short(_summary_text(qa), 220)}")
        if _summary_text(reviewer):
            lines.append(f"reviewer routing summary: {_short(_summary_text(reviewer), 220)}")
        lines.append("mode: inspect changes, push branch, create PR with curl + GITHUB_TOKEN, use gh for PR metadata/checks; PASS is allowed when no checks are configured and pr_checks.checks_required=false")
    else:
        lines.append("custom role prompt is passed as-is")
    return lines
