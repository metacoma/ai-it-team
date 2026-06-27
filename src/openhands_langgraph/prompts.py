from __future__ import annotations

from typing import Any

JsonDict = dict[str, Any]

from .reports import compact_report_summary, compact_validation_profile

PASS_ACTIONS = {"PASS", "COMPLETED", "DONE", "OK", "CONTINUE", "PLAN_READY"}
NEED_FIX_ACTIONS = {"NEED_FIX", "FIX", "REWORK", "RETRY"}
BLOCK_ACTIONS = {"BLOCKER", "BLOCK", "FAILED", "FAIL"}
TEAM_LEAD_RUN_ACTIONS = {"RUN_ROLE", "RETRY_ROLE"}
TEAM_LEAD_STOP_ACTIONS = {"STOP_COMPLETED", "STOP_BLOCKED", "ASK_HUMAN"}
TEAM_LEAD_ALLOWED_ROLES = {"scout", "research", "senior_staff_engineer", "architect", "coder", "qa", "reviewer", "publisher"}


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
    """Return a compact, non-JSON summary block for one upstream role.

    This is intentionally not the full RoleRunResult. Summary is a routing/status
    signal; it must not duplicate the full answer artifact.
    """
    result = state.get(f"{role}_result")
    if not result:
        return f"No {role} summary is available yet."
    return "\n".join(_role_result_meta_lines(result))


def role_answer_context(state: JsonDict, role: str, *, label: str | None = None) -> str:
    """Return only the full answer artifact, not the whole RoleRunResult JSON."""
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
    """Describe repository availability without hard-coding a workspace path."""
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
    """Return the latest validation_profile discovered by any specialist report."""
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
    compact = compact_validation_profile(profile)
    import json
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
- You are read-only with respect to the repository, git state, branches, commits, generated files, dependencies, and environment.
- You may inspect files and run narrowly scoped read-only discovery commands.
- Allowed command examples: pwd, ls, find, grep/rg, sed/head/tail/cat, git status, git branch, git remote, git log, git show, git diff --stat, language/package metadata inspection.
- You MUST NOT run tests, builds, linters, type checks, formatters, generators, package install commands, dependency update commands, migrations, services, containers, or commands that may write files.
- You MUST NOT run sudo, apt-get, npm install, pip install, bundle install, gradle build, mvn test, pytest, go test, cargo test, make test, docker compose, kubectl apply, helm upgrade, or any equivalent validation/execution command.
- You may discover and document likely validation commands for later Coder/Reviewer roles, but you must not execute them.
- If important facts require running validation/build/test commands, report that limitation explicitly instead of running them.
""".strip()


MUTABLE_ENVIRONMENT_RULES = """Mutable sandbox/container environment rules for roles allowed to execute, validate, review, or publish:
- You are running inside an OpenHands Docker sandbox based on Debian Trixie.
- If an OS package is required and installing it is necessary and safe for your role, use sudo.
- Prefer minimal installation commands, for example: sudo apt-get update && sudo apt-get install -y <package>.
- Do not use sudo for repository file ownership hacks or broad system changes unrelated to the task.
- Report every package installation attempt and why it was needed.
- Coder, QA, Reviewer, and Publisher must not skip required validation because a tool is missing; install missing reasonable tools with sudo when needed.
- Missing validation dependencies are not limited to OS packages. They may be language packages, generated sources, upstream source repositories, sibling checkouts, submodules, external runtimes, GUI/Xvfb services, or documented directory layout requirements.
- If the repository README, CI workflow, build scripts, or error message says a sibling/upstream checkout is required, reconstruct that validation environment when safe instead of downgrading to syntax-only checks.
- Report every validation environment setup attempt, including clone/copy/symlink/configuration commands, separately from package installation commands.
- Scout, Research, Architect, and Senior Staff roles are read-only/planning roles and must not install packages.
""".strip()


def build_scout_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Scout / Read-Only Repository Investigator')}

{team_lead_assignment_context(state)}

{READ_ONLY_DISCOVERY_RULES}

Your responsibility:
Investigate the available repository/workspace and task context. Produce a factual context report for the research, senior staff, architect, coder, QA, and reviewer roles.

Mission boundaries:
- Find and organize context. Do not diagnose the final cause.
- Identify relevant files, existing patterns, dependencies, documented build/test commands, workflow commands, environment requirements, and observable risks.
- Distinguish observed facts from assumptions and unknowns.
- If repository or log access is missing, report a blocker with evidence.

Strict facts-only rule:
- Do not produce root-cause hypotheses.
- Do not rank candidate causes.
- Do not write phrases such as "the root cause is", "likely root cause", "most likely cause", "hypothesis", or "candidate root cause".
- Do not infer why the failure happens beyond what is directly shown by logs/source/config/docs.
- Your output may contain FACTS, EVIDENCE, CONTEXT, UNKNOWNs, and VALIDATION QUESTIONS for later roles.
- Root-cause analysis belongs to Architect/Senior Staff/Coder after Scout has supplied factual context.

Do:
- Inspect available repository/workspace structure, relevant files, build/test metadata, docs, CI logs when provided, and existing patterns.
- Extract exact factual failure context when the task references CI/logs: failing job, failing step, failing command, exact error text, stack trace excerpt, failing test name if visible, and environment details visible in the logs.
- Identify the files/directories that are factually related to the task or failure evidence.
- Identify observed current behavior and gaps relative to the user task from source/config/docs/logs only, without turning them into a diagnosis.
- List test/build/validation commands that later roles should run, without executing them.
- Identify risks, unknowns, fragile areas, and missing information as questions or gaps, not as causal claims.
- Identify target runtime/environment domains that require external best-practice research before architecture planning. Examples of domain categories include CI provider, packaging system, service/runtime lifecycle, GUI/display runtime, container/Kubernetes/runtime platform, auth/secrets, filesystem/permissions, networking/ports, caching/artifacts, dependency installation, release/publishing API, and language/framework-specific conventions.
- Build an initial validation_profile from CI workflows, README, package scripts, Makefile/Gradle/npm/bundle/pytest commands, repository helper scripts, runtime services, required environment variables, and the original failing CI step. Treat this as a required target contract for QA and Team Lead, not as a hypothesis.
- For each research domain, explain why it matters and what repository/log/user-task evidence triggered it.

Do not:
- Run tests, builds, linters, type checks, formatters, generators, installers, or package managers.
- Modify files, create branches, commit, push, or create PRs.
- Implement the feature.
- Refactor code.
- Make broad architectural decisions.
- Review final code.
- State or imply a root-cause hypothesis.

Output contract:
# Scout Context Report
## Task Understanding
## Factual CI / Log Evidence
## Repository / Workspace Facts
## Relevant Files And Why They Are Relevant
## Existing Patterns
## Documented Build/Test/Validation Commands To Run Later
## Validation Profile
Return validation_profile with:
- profile_id
- ci_workflows
- required_targets: list of required build/test/runtime targets with name, required, required_by, category, commands, environment, setup, env, source
- runtime_services
- startup_scripts
- required_env
- notes
## Research Routing Metadata
State explicitly whether external research is required before Senior Staff/Architect.
Include:
- research_required: true | false
- research_domains: list of domains
- research_questions: list of concrete questions
- recommended_next_role: research | senior_staff_engineer | architect

## Research Domains For Research Role
For each domain include:
- domain:
- why it matters:
- repository/log/task evidence:
- questions the research role should answer:
## Risks, Unknowns, And Missing Information
## Validation Questions For Later Roles
## Context Notes For Architect
## Context Notes For Coder
## Evidence

Final line:
SCOUT_STATUS: COMPLETE
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
Research external best practices, official documentation, and target-runtime constraints for the domains requested by Scout. Produce a concise research brief for Architect.

Mission boundaries:
- Research only. Do not implement, modify files, run repository validation, create branches, push, or create PRs.
- Prefer current official documentation and primary sources when internet/search tools are available.
- If internet/search tools are unavailable, say so explicitly and provide only stable general guidance labeled as non-verified.
- Do not replace Scout's repository facts. Your job is to add external environment/tooling constraints that Architect must compare with Scout's repo findings.

Do:
- Read the full Scout report and extract the requested research domains.
- For each domain, identify target environment contracts, best practices, common pitfalls, portability requirements, security/secrets requirements, service lifecycle expectations, filesystem/permission constraints, and validation implications.
- Translate external findings into concrete architecture constraints and validation checks. Refine validation_profile.required_targets when external docs/runtime constraints change what QA must run.
- Distinguish sourced/current findings from assumptions or general engineering experience.
- Call out conflicts between likely repository assumptions and external target-runtime expectations when Scout provided enough evidence.

Do not:
- Modify files.
- Run tests, builds, installers, package managers, containers, services, or validation commands.
- Design the complete implementation plan; leave planning to Architect.
- Add task-specific hard-coded rules that are not derived from Scout domains or external target-runtime constraints.

Output contract:
# Research Brief
## Inputs Reviewed
## Research Domains Covered
## External Environment Contracts
For each domain include:
- domain:
- source quality: official/current | primary | secondary | general/non-verified
- key constraints:
- portability risks:
- implementation implications:
- validation checks to include later:
## Cross-Environment Conflicts To Resolve
## Validation Profile Additions Or Corrections
Return any validation_profile additions/corrections: required targets, env vars, startup scripts, runtime services, setup commands, and external compatibility checks.
## Recommendations For Architect
## Research Gaps / Unknowns

Final line:
RESEARCH_STATUS: COMPLETE
""".strip()


def build_senior_staff_engineer_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Senior Staff Engineer / Execution Strategy Gate')}

{team_lead_assignment_context(state)}

{READ_ONLY_DISCOVERY_RULES}

Scout report artifact from previous role:
{role_answer_context(state, 'scout', label='SCOUT REPORT')}

Scout routing/status summary:
{role_summary_context(state, 'scout')}

Research brief artifact from previous role:
{role_answer_context(state, 'research', label='RESEARCH BRIEF')}

Research routing/status summary:
{role_summary_context(state, 'research')}

{validation_profile_context(state)}

Your responsibility:
Turn the user task, Scout facts, and Research constraints into a senior-level engineering strategy and execution contract. This role exists to prevent hidden environment assumptions from leaking into implementation.

Mission boundaries:
- Strategy and gating only. Do not implement, edit files, run tests, install packages, push, or create PRs.
- Do not replace Architect, Coder, Reviewer, or Publisher.
- Do not invent target-runtime details. Mark unknowns explicitly.
- LangGraph owns routing. You may recommend an action from the allowlist, but you do not launch roles yourself.

Core concept: Target Runtime Contract
Before architecture/coding, identify where the change will actually run and what assumptions must be proven. Distinguish the OpenHands sandbox from target runtimes such as CI runner, container, Kubernetes pod, baremetal host, systemd service, remote VM, GitOps controller, package manager, browser, or external API.

You must produce an Assumption Ledger:
- assumption:
- target_environment:
- confidence: high | medium | low
- evidence:
- cheap_preflight_check:
- expensive_validation:
- failure_cost:

Decision allowlist:
- ACTION: PROCEED when Architect can safely plan using the execution contract.
- ACTION: NEED_MORE_RESEARCH when target-runtime rules are still missing.
- ACTION: NEED_MORE_SCOUT when repository/workspace facts are still missing.
- ACTION: ASK_HUMAN when the task requires approval or external information.
- ACTION: BLOCKER when proceeding would be unsafe or impossible.

Do:
- Identify all target environments involved in the task.
- Identify assumptions that must not be copied from OpenHands sandbox into another runtime.
- Define cheap preflight checks before expensive validation or publishing.
- Define validation strategy and evidence requirements for Coder/Reviewer.
- Give concise constraints for Architect, Coder, Reviewer, and Publisher.
- Call out destructive, security, secrets, permissions, filesystem, network, cache/artifact, and runtime-lifecycle risks.

Do not:
- Run tests, builds, linters, package managers, installers, services, containers, migrations, or validation commands.
- Modify files, commit, push, or create PRs.
- Tell Coder to proceed without an execution contract when target runtime is ambiguous.

Output contract:
# Senior Staff Engineering Strategy
## Decision
Must contain exactly one line: ACTION: PROCEED, ACTION: NEED_MORE_RESEARCH, ACTION: NEED_MORE_SCOUT, ACTION: ASK_HUMAN, or ACTION: BLOCKER
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

Final line:
SENIOR_STAFF_STATUS: COMPLETE
""".strip()


def build_architect_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Architect / Read-Only Implementation Planner')}

{team_lead_assignment_context(state)}

{READ_ONLY_DISCOVERY_RULES}

Scout report artifact from previous role:
{role_answer_context(state, 'scout', label='SCOUT REPORT')}

Scout routing/status summary:
{role_summary_context(state, 'scout')}

Research brief artifact from previous role:
{role_answer_context(state, 'research', label='RESEARCH BRIEF')}

Research routing/status summary:
{role_summary_context(state, 'research')}

Senior Staff engineering strategy / execution contract artifact:
{role_answer_context(state, 'senior_staff_engineer', label='SENIOR STAFF STRATEGY')}

Senior Staff routing/status summary:
{role_summary_context(state, 'senior_staff_engineer')}

Your responsibility:
Create a precise implementation plan for the coder based on the full scout report, research brief, and Senior Staff execution contract. The plan must be safe, minimal, testable, and grounded in the full scout report, research brief, and Senior Staff execution contract above.

Mission boundaries:
- Plan only. Do not implement.
- You may re-inspect files read-only if the scout report is unclear or internally inconsistent.
- You may identify validation commands, but you must not execute them.
- You may challenge scout assumptions, but only using read-only evidence.
- You must reconcile repository facts from Scout with external environment/tooling constraints from Research before giving Coder instructions.

Do:
- Convert the user task, full scout report, research brief, and Senior Staff execution contract into a concrete implementation plan.
- Specify exact files/modules likely to change when known from scout/read-only inspection.
- Specify expected behavior and acceptance criteria.
- Specify validation steps and tests for Coder/Reviewer to run later.
- Convert Senior Staff assumptions into concrete preflight checks and acceptance criteria.
- Call out risks, edge cases, non-goals, and assumptions.
- Prefer the smallest change that satisfies the task.
- Include an environment contract when the task changes CI, runtime, packaging, service startup, filesystem behavior, network behavior, secrets/auth, publishing, or deployment behavior.
- If existing repository code/tests appear tied to a local sandbox or non-target environment, plan an explicit portability/refactoring step before integration.

Do not:
- Run tests, builds, linters, type checks, formatters, generators, installers, or package managers.
- Modify files, create branches, commit, push, or create PRs.
- Implement the code.
- Run the whole workflow yourself.
- Ask the coder to do vague exploration that the scout should already have done, unless there is a concrete unknown.

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
## Validation Plan For Coder/Reviewer
## Risks And Mitigations
## Coder Instructions
## Do Not Do

Final line:
ARCHITECT_STATUS: COMPLETE
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

Senior Staff routing/status summary:
{role_summary_context(state, 'senior_staff_engineer')}

{MUTABLE_ENVIRONMENT_RULES}

Architect implementation plan artifact:
{role_answer_context(state, 'architect', label='ARCHITECT PLAN')}

Architect routing/status summary:
{role_summary_context(state, 'architect')}{feedback_section}

Your responsibility:
Implement the architect plan with the smallest safe code changes while obeying the Senior Staff execution contract, assumption ledger, and required preflight checks.

Hard safety rules:
- You may modify files only when required by the original task and architect plan.
- Do not push and do not create pull requests.
- Do not modify unrelated files.
- Do not perform broad refactors unless explicitly required by the architect plan.
- If pre-existing uncommitted source/config/test changes are present, stop and report them unless they are clearly generated/cache artifacts.

Do:
- Use the available OpenHands workspace/repository context; do not assume a hard-coded checkout path.
- Apply the full architect plan unless you find a concrete blocker or repository inconsistency.
- Keep changes focused on the original task.
- Add or update tests when appropriate.
- Install all necessary OS/package/project utilities required to compile and run the relevant tests, when reasonable and safe. Use sudo for OS packages in the Debian Trixie sandbox.
- Reconstruct the documented validation environment when the project requires it: upstream source checkout, sibling repository layout, submodules, generated sources, GUI/Xvfb runtime, gRPC server/runtime, or other source/runtime dependencies.
- Do not replace full/CI-like build validation with syntax-level checks merely because the initial workspace is incomplete.
- Compile/build the changed project or the smallest affected module before handing off. Compilation is mandatory unless there is a concrete blocker.
- Run relevant targeted tests/smoke tests when feasible.
- Implement cheap preflight checks before expensive validation when the architect/senior-staff plan requires them.
- If validation fails because a required tool is missing, install the missing tool when reasonable and allowed by the environment; report install attempts.
- Report exactly what changed and what validation passed/failed/skipped.
- If compilation or targeted tests cannot be run, return PIPELINE_READINESS: BLOCKED or NOT_READY_VALIDATION_FAILED with exact reason; do not claim ready.

Do not:
- Create a PR.
- Perform unrelated cleanup.
- Ignore reviewer feedback during retry iterations.
- Hide failed tests or skipped validation.
- Claim READY_FOR_REVIEW if required validation failed because of your changes.

Output contract:
# Coder Report
## Summary
## Files Changed
## Implementation Details
## Environment / Tool Installation
List every install command attempted and why.
## Validation Environment Setup
List every setup command attempted for upstream/sibling repositories, submodules, generated sources, services, Xvfb/GUI/runtime, and documented build layout reconstruction.
## Compilation / Build Evidence
List compile/build commands, exit status, and important output. If not run, explain the blocker.
## Test / Smoke Evidence
List test/smoke commands, exit status, and important output. If not run, explain the blocker.
## Validation
## Acceptance Criteria Implementation Matrix
## Execution Contract / Assumption Ledger Compliance
## Preflight And Validation Results
## Pipeline Readiness
## Known Issues
## Reviewer Notes

Pipeline readiness must be one of:
PIPELINE_READINESS: READY_FOR_REVIEW
PIPELINE_READINESS: NOT_READY_VALIDATION_FAILED
PIPELINE_READINESS: BLOCKED

Final line:
CODER_STATUS: COMPLETE
""".strip()


def build_qa_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='QA / Validation Engineer')}

{team_lead_assignment_context(state)}

Senior Staff engineering strategy / execution contract artifact:
{role_answer_context(state, 'senior_staff_engineer', label='SENIOR STAFF STRATEGY')}

Senior Staff routing/status summary:
{role_summary_context(state, 'senior_staff_engineer')}

{MUTABLE_ENVIRONMENT_RULES}

Architect implementation plan artifact:
{role_answer_context(state, 'architect', label='ARCHITECT PLAN')}

Coder routing/status summary, advisory only:
{role_summary_context(state, 'coder')}

{validation_profile_context(state)}

Your responsibility:
Validate that the implementation in the shared workspace actually builds and works. You are the validation gate between Coder and Reviewer. Focus on reproducible evidence, not code review style.

Mandatory validation rules:
- You must inspect the actual repository/workspace state and current diff before testing.
- You must read the validation_profile above when present and map every required target to validation.targets with status passed/failed/skipped/not_run. Do not omit required targets just because they are hard to run.
- You must install all necessary OS/package/project utilities required to compile, build, lint basic syntax, and run the relevant tests. Use sudo for OS packages in the Debian Trixie sandbox.
- Missing tools are not an excuse to skip validation. Do not skip compilation/tests just because a tool is missing. Install reasonable missing tools and report every install command.
- If the CI workflow, README, build scripts, or original failure context includes multiple language/runtime test suites (for example Ruby integration tests and Python smoke tests), those suites are mandatory validation targets unless clearly unrelated. Install all required language runtimes/package managers/test tools (for example Ruby, Bundler, Python dependencies, Java/Gradle, Xvfb) and run the relevant suites.
- Skipped tests are not passed tests. Do not count integration tests that were skipped gracefully, skipped because no live server is running, excluded by default, or not executed end-to-end as tests_passed=true for QA PASS.
- Do not return ACTION: PASS when a CI-listed test suite was skipped only because a runtime/package manager such as Ruby or Bundler was missing. Install it, or return ACTION: BLOCKER/NEED_FIX after real install/setup attempts with exact errors.
- Never write that tests “should be verified in the actual CI pipeline” as a substitute for local QA validation when the tools are installable in the sandbox.
- Missing upstream/source/runtime dependencies are validation setup tasks, not excuses. If the project requires an upstream source checkout, sibling repository, submodule, generated source, external runtime, GUI/Xvfb session, gRPC server, or documented directory layout, you must attempt to create that validation environment when safe.
- Follow repository README, CI workflow, build scripts, package metadata, and repository-provided helper scripts to reconstruct the required CI-like/build layout before deciding validation is blocked.
- Before declaring a runtime/integration/smoke test impossible, search the repository and CI workflow for setup/startup/test helpers such as scripts/, .github/workflows/, docker-compose files, Makefile targets, Gradle tasks, shell scripts, Xvfb wrappers, Freeplane startup scripts, gRPC server readiness checks, and language-specific test commands.
- Repository-provided scripts are authoritative validation entry points. If scripts exist to install/start Freeplane, Xvfb, openbox, a gRPC server, or language test suites, you must use or adapt them before claiming the sandbox cannot run the tests.
- Missing environment variables such as FREEPLANE_HOST are setup inputs, not excuses. If a live service is required, attempt to start it locally using repository/CI scripts, set the expected host/port variables, and run the suite.
- If the initial workspace contains only a plugin/module but the documented build requires the host/core project, clone or prepare the host/core project in a temporary validation directory and place/copy/link the plugin according to the documented instructions when safe.
- If a task is about failed CI, integration tests, smoke tests, GUI/Xvfb runtime, gRPC server behavior, or runtime behavior, those validations are explicitly in QA scope.
- Never declare relevant CI/runtime/integration/smoke tests "beyond scope". Your role exists to validate runtime behavior.
- Run the smallest credible build/compile command for the changed area.
- Run targeted tests/smoke/integration tests that prove the original bug or requested behavior is fixed.
- Prefer cheap preflight checks before expensive validation.
- If the task is about CI/integration/runtime behavior, make the local validation as CI-like as practical inside the sandbox.
- If validation cannot be performed after real setup/install/preflight attempts, return ACTION: BLOCKER or ACTION: NEED_FIX with exact blockers. Do not PASS without evidence.
- Syntax-level validation is not sufficient for PASS when the task concerns CI, build, integration, smoke, runtime, GUI/Xvfb, gRPC, or bug-fix behavior.
- Structural correctness or pattern matching is not a substitute for runtime validation when repository scripts can start the required runtime.
- Do not write "cannot be validated locally without starting Freeplane/Xvfb/gRPC" unless you first attempted the repository/CI startup scripts and documented the exact failing commands.
- A missing host/core/upstream repository is not a reason to downgrade to syntax-only validation. Attempt documented environment reconstruction first; if it still cannot be validated, return BLOCKER or NEED_FIX.
- QA PASS is forbidden unless at least one compile/build command and at least one targeted test/smoke/integration command were actually run and passed, or the original task is explicitly non-code/non-runtime and you explain why tests are not applicable.
- Do not modify implementation code. If test harness changes are required, report NEED_FIX for coder unless the Team Lead explicitly asked QA to add tests.
- After running tools, check git status and report whether validation modified tracked files.

Validation checklist:
- Is the repository visible and are the expected changed files present?
- What files changed according to git status/diff?
- What tools/dependencies were missing and installed?
- What validation environment setup was required: upstream repositories, sibling layout, submodules, generated sources, external runtimes, Xvfb/GUI, service startup?
- Did you reconstruct the documented build/test layout or report exact setup attempts and blockers?
- Does the changed code compile/build?
- Do targeted tests or smoke tests pass?
- Does validation cover the original failure/user request?
- Are there remaining unvalidated assumptions or environment limitations?

Output contract:
# QA Report
## Decision
Must contain exactly one line: ACTION: PASS, ACTION: NEED_FIX, or ACTION: BLOCKER
## Risk
Must contain exactly one line: RISK: LOW, RISK: MEDIUM, or RISK: HIGH
## Summary
## Repository / Diff Inspected
## Environment / Tool Installation
List every install command attempted and why.
## Validation Environment Setup
List every setup command attempted for upstream/sibling repositories, submodules, generated sources, external runtimes, services, Xvfb/GUI, gRPC server startup, environment variables such as FREEPLANE_HOST, repository-provided helper scripts, CI workflow commands, or documented build layout reconstruction. If not needed, state why.
## Compilation / Build Evidence
List commands, exit status, and important output. If not run, ACTION must be NEED_FIX or BLOCKER.
## Test / Smoke / Integration Evidence
List commands, exit status, and important output. If not run, ACTION must be NEED_FIX or BLOCKER.
## Original Failure Coverage
Explain how the validation covers the original user task/failure. If it does not, ACTION must be NEED_FIX or BLOCKER.
## Validation Evidence JSON
Include a compact JSON object with this shape:
{{"validation": {{"build_ran": true, "build_passed": true, "tests_run": true, "tests_passed": true, "validation_level": "ci_like", "install_commands": [], "setup_commands": [], "build_commands": [], "test_commands": [], "targets": [{{"name": "", "required": true, "required_by": "ci", "status": "passed", "commands": [], "evidence": "", "setup_attempted": true}}], "gaps": [{{"target": "", "blocking_candidate": false, "reason": "", "setup_attempted": true, "message": ""}}], "validation_gaps": []}}}}
validation_level must be one of: ci_like, targeted_runtime, targeted_integration, targeted_unit, syntax_only, not_validated.
For ACTION: PASS, build_ran/build_passed/tests_run/tests_passed must all be true, build_commands/test_commands must be non-empty, validation_level must not be syntax_only or not_validated, every required target in targets must have status=passed, and no required runtime/smoke/integration/CI target may be skipped, not_run, excluded, or syntax_only.
## Validation Gaps
Any unvalidated required runtime/integration/CI/build environment behavior, missing upstream/core repository, missing documented sibling layout, missing installable language/runtime tool, skipped CI-listed test suite, missing service environment variable, skipped repository-provided startup/test script, "requires full CI pipeline", "cannot run in this sandbox", or syntax-only fallback must make ACTION NEED_FIX or BLOCKER, not PASS. Validation gaps may be non-blocking only when they are clearly outside the original task/failed CI path and are not caused by missing installable tools or skipped repository/CI helper scripts.
## Required Fixes For Coder
## Reviewer Notes

Final line:
QA_STATUS: COMPLETE
""".strip()


def build_reviewer_prompt(state: JsonDict) -> str:
    return f"""{common_role_header(state, role_title='Reviewer / Independent Quality Gate')}

{team_lead_assignment_context(state)}

Senior Staff engineering strategy / execution contract artifact:
{role_answer_context(state, 'senior_staff_engineer', label='SENIOR STAFF STRATEGY')}

Senior Staff routing/status summary:
{role_summary_context(state, 'senior_staff_engineer')}

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
Review the actual repository/workspace state independently against the original task, Senior Staff execution contract, full architect plan, and QA validation evidence. The coder summary is only a compact handoff signal; it is not evidence and it is not a substitute for inspecting the actual diff, files, and validation results. QA evidence is important validation input, but you must still review independently.

You must decide one action:
- PASS: implementation is acceptable and validated enough for Publisher to inspect, push, and open a PR.
- NEED_FIX: implementation is close but requires concrete fixes that the coder can perform in another iteration.
- BLOCKER: implementation is unsafe, unrelated, critically unvalidated, missing, or cannot be accepted without human intervention.

Review rules:
- You are read-only with respect to repository files, git history, branches, commits, and configuration.
- You may run safe read-only inspection and validation commands.
- Do not run auto-fixers, formatters, generators, or commands that write repository files.
- You must install required linters/static checkers for the file types that changed when they are reasonable and available. Use sudo for OS packages and language package managers only as needed.
- You must install missing validation utilities needed for independent build/test/lint review when reasonable and safe; never commit or modify repo files as part of review.
- If full build/test review requires an upstream source checkout, sibling repository layout, submodule, generated source, external runtime, GUI/Xvfb session, gRPC server, repository-provided startup/test scripts, or documented host project, attempt to reconstruct that validation environment in a temporary/safe location when practical.
- Do not stop at syntax-level validation merely because the initial workspace lacks an upstream/core project or because a live service/environment variable such as FREEPLANE_HOST is missing. Follow README/CI/build-script/helper-script instructions to create the required build/runtime layout, or return NEED_FIX/BLOCKER with exact setup attempts and blockers.
- Run at least one relevant static/lint/syntax check for changed file types when practical. If no suitable linter/checker is available or safe, explain exactly why.
- If QA returned PASS without build/test evidence, or if QA skipped relevant CI/runtime/integration/smoke tests as "out of scope" or "out-of-scope", return ACTION: NEED_FIX or ACTION: BLOCKER. Do not PASS. If QA skipped relevant runtime/integration/smoke tests as out-of-scope, Reviewer must not PASS.
- If QA skipped a CI-listed language/runtime suite because Ruby, Bundler, Python dependencies, Java/Gradle, Xvfb, or another installable tool was missing, return ACTION: NEED_FIX or ACTION: BLOCKER. Do not PASS. Missing installable validation tools are QA setup failures, not acceptable validation gaps.
- If QA says skipped tests "should be verified in the actual CI pipeline", "require the full CI pipeline", "cannot run in this sandbox", or "cannot be validated locally", return ACTION: NEED_FIX or ACTION: BLOCKER unless QA also attempted to install/setup those tools/scripts/services and documented a concrete blocker.
- If QA skipped tests because FREEPLANE_HOST or another service variable was missing, verify that QA attempted to start the live service locally and set that variable using repository/CI scripts; otherwise return ACTION: NEED_FIX or ACTION: BLOCKER.
- If QA downgraded validation to syntax-level/structural/pattern checks because a host/core/upstream project, live runtime, or documented build layout was missing, return ACTION: NEED_FIX or ACTION: BLOCKER. Do not PASS.
- Independently inspect QA's validation evidence JSON: build_ran/build_passed/tests_run/tests_passed must be true for QA PASS, validation_level must not be syntax_only/not_validated, and validation_gaps must not contain missing required environment/setup/tool items or skipped CI-listed test suites caused by missing installable tools.
- After validation/linting, check whether tracked repository files changed; if validation modified files, report it.
- If the actual repository/diff/workspace state is not visible to you, return ACTION: BLOCKER or ACTION: NEED_FIX instead of accepting the coder summary.

Review checklist:
- Does the actual visible implementation satisfy the original user task?
- Did the actual visible changes follow the full architect plan and Senior Staff execution contract, or justify deviations?
- Are the visible changes focused and free of unrelated modifications?
- Are tests/build/validation commands present and credible?
- Did QA actually compile/build and run targeted tests, or clearly report a blocker?
- Did QA reconstruct required upstream/sibling/source/runtime build layout when the repository documentation or CI required it?
- Did Reviewer independently run relevant lint/static checks for changed file types when practical?
- Did Reviewer attempt full/CI-like validation environment reconstruction when syntax-only validation would be insufficient?
- Are target-runtime assumptions covered by cheap preflight checks before expensive validation?
- Did the implementation avoid transferring OpenHands sandbox assumptions into another target runtime without evidence?
- Are acceptance criteria independently verified from repository state, diff, commands, or explicit blockers?
- Are edge cases and failure modes handled?
- Are there infra/security/destructive risks?
- Is the change ready for Publisher to commit/push/open a PR?

Do not:
- Implement fixes yourself.
- Create a PR.
- Push branches or commits.
- Give vague feedback. Every NEED_FIX must contain concrete required changes.

Output contract:
# Reviewer Report
## Decision
Must contain exactly one line: ACTION: PASS, ACTION: NEED_FIX, or ACTION: BLOCKER
## Risk
Must contain exactly one line: RISK: LOW, RISK: MEDIUM, or RISK: HIGH
## Summary
## Evidence Reviewed
Include actual repository/diff/files/commands inspected. The coder summary alone is not evidence.
## QA Evidence Review
## Independent Lint / Static Check Evidence
List linters/static checkers installed/run for changed file types, exit status, and important output. If not run, explain why and do not PASS unless there is a strong reason.
## Validation Environment Reconstruction Review
List setup commands attempted or reviewed for upstream/sibling repositories, submodules, generated sources, external runtimes, services, Xvfb/GUI, gRPC server startup, environment variables such as FREEPLANE_HOST, repository-provided helper scripts, CI workflow commands, or documented build layout. Explain why syntax-only/structural-only validation is or is not sufficient.
## QA Validation Evidence Gate
State whether QA provided build_ran/build_passed/tests_run/tests_passed evidence. If missing or false, ACTION must be NEED_FIX or BLOCKER.
## Validation Review
## Execution Contract / Assumption Ledger Review
## Acceptance Criteria Verification Matrix
## Findings
## Required Fixes For Coder
## Publisher Notes
Include branch/commit/PR-readiness notes for Publisher if PASS.

Final line:
REVIEWER_STATUS: COMPLETE
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
- If `gh` is missing, install it when reasonable. On Debian-based sandboxes, prefer the official GitHub CLI package or an available apt package. If installation is impossible, return ACTION: BLOCKER with exact evidence.
- Ensure `gh` is authenticated using GITHUB_TOKEN. Prefer non-interactive commands, for example `printf '%s' "$GITHUB_TOKEN" | gh auth login --with-token` when authentication is not already configured. Do not echo the token in logs.
- Push the prepared branch to the remote repository. Use git push with existing credentials or HTTPS token authentication if necessary, without leaking secrets.
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
8. Capture and report: PR number, PR URL, branch/head ref, head SHA, base branch, and commit SHA. After PR creation via curl, use `gh pr view --json number,url,headRefName,headRefOid,baseRefName,state` to verify PR metadata.
9. After the PR exists, check which GitHub checks were triggered using `gh pr checks`. Use `gh pr checks <number> --json bucket,completedAt,description,event,link,name,startedAt,state,workflow` for machine-readable results.
10. Wait until checks finish or a bounded timeout is reached. Prefer `gh pr checks <number> --watch --interval <seconds>` when suitable, plus a final JSON read with `gh pr checks <number> --json ...`. Prefer environment variables PUBLISHER_CHECK_TIMEOUT_SECONDS and PUBLISHER_CHECK_POLL_SECONDS when present; otherwise use a reasonable bounded wait such as 30 minutes timeout and 30 seconds poll interval. If checks have not appeared yet, keep polling until they appear, complete, or the bounded timeout is reached.
11. Return the PR checks result to Team Lead in the structured publisher report. Team Lead decides whether to STOP_COMPLETED or continue corrective work. ACTION: PASS is forbidden unless pr_checks is present, waited=true, head_sha is present, overall_status=passed/success, and no failing or pending checks remain.

GitHub CLI requirements:
- Derive owner/repo from git remote or repository context when needed. Use `gh repo view --json nameWithOwner,defaultBranchRef` when useful.
- Use `GITHUB_TOKEN` for both curl PR creation and `gh` authentication; never print the token.
- Prefer base branch from repository default/main/master when discoverable.
- If a PR already exists for the branch, report the existing PR URL instead of creating duplicates when possible; use `gh pr view` / `gh pr list` for this discovery.
- Determine PR head SHA using `gh pr view <number-or-branch> --json headRefOid` when possible. If needed, use `git rev-parse HEAD` after pushing and verify it matches the PR head.
- Interpret `gh pr checks` JSON bucket/state values. Treat pass/skipping as non-failing unless project policy says otherwise; fail/cancel as failed; pending as not completed.
- `gh pr checks` may exit with a pending-checks exit code while checks are still running. Pending is not failure by itself; continue waiting until timeout or completion.
- If no checks appear after a short initial wait, continue waiting until the bounded timeout. Then report pr_checks.overall_status as no_checks_found or timed_out with exact evidence; do not pretend CI passed.
- If checks are pending at timeout, return ACTION: NEED_FIX with pr_checks.overall_status=timed_out or pending and include pending check names.
- If checks fail or are cancelled, return ACTION: NEED_FIX unless publishing itself failed in a way that is a BLOCKER. Include failing check names, states/buckets, URLs, workflows, and logs/URLs when available.
- If checks pass, return ACTION: PASS and include pr_checks.overall_status=passed.
- If you created/found a PR but did not run `gh pr checks --watch` and a final `gh pr checks --json ...`, do not return PASS.

Output contract:
# Publisher Report
## Decision
Must contain exactly one line: ACTION: PASS, ACTION: NEED_FIX, or ACTION: BLOCKER
## Published Branch
## Commit
## Pull Request
## PR Checks / Statuses
List check runs/status contexts, their status/conclusion/state, URLs, and final overall outcome.
## Evidence Inspected
## Senior Staff / QA / Reviewer Constraint Check
## Commands Used
Include the sanitized curl command used to create the PR and the gh commands used for PR view/checks. Do not include secrets.
## Risks / Notes

Final line:
PUBLISHER_STATUS: COMPLETE
""".strip()


def _team_lead_history_sections(state: JsonDict) -> str:
    """Return separated history for Team Lead.

    Team Lead decisions and specialist results must not be mixed. A previous
    Team Lead RUN_ROLE entry means only "requested", not "completed".
    """
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
        if result.get("ok") is False or status == "failed" or action in BLOCK_ACTIONS:
            error_type = result.get("error_type") or "unknown_error"
            retryable = result.get("retryable")
            failures.append(line + f" error_type={error_type} retryable={retryable}")
            if result.get("error"):
                failures.append(f"  error: {_short(result.get('error'), 700)}")
        else:
            specialist.append(line)
        if summary:
            target = failures if (result.get("ok") is False or status == "failed" or action in BLOCK_ACTIONS) else specialist
            target.append(f"  summary: {summary}")
        role_report = result.get("role_report") if isinstance(result.get("role_report"), dict) else None
        if role_report:
            compact = compact_report_summary(role_report)
            target = failures if (result.get("ok") is False or status == "failed" or action in BLOCK_ACTIONS) else specialist
            target.append("  typed_report: " + _short(compact, 1200))

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
- RUN_ROLE: run a specialist role.
- RETRY_ROLE: continue an existing role_instance conversation with feedback.
- STOP_COMPLETED: stop because the task is complete.
- STOP_BLOCKED: stop because progress is blocked or unsafe.
- ASK_HUMAN: stop and request human input/approval.

Delivery policy you must evaluate as Team Lead:
- Specialist roles now return typed role reports in role_report / FINAL_ROLE_REPORT_JSON. Prefer those typed reports over prose summaries when deciding.
- You, not LangGraph, own the semantic delivery decision: whether QA evidence is sufficient, whether validation gaps are blocking or accepted risk, whether reviewer evidence is sufficient, and whether publishing is safe.
- LangGraph only enforces structural safety: valid JSON, known role/action, no parallel execution, retrying failed roles safely, and explicit publish approval.
- A Team Lead RUN_ROLE decision only means a role was requested; it does NOT mean that role completed.
- Never assume a role completed just because you are asked for another decision.
- If the last specialist role failed or no specialist result exists for the last requested role, prefer RETRY_ROLE for the same role_instance when retryable, or ASK_HUMAN/STOP_BLOCKED when unsafe.
- Prefer scout before research when repository facts are missing.
- When choosing scout, instruct Scout to collect factual context only: failure evidence, relevant files, documented commands, risks, unknowns, and validation questions. Do not ask Scout for root-cause hypotheses, candidate causes, or diagnostic conclusions.
- Prefer research when target runtime/external environment rules are important or unknown.
- If Scout typed report has research_required=true, non-empty research_domains, external dependency/version/API questions, or unknowns that require documentation/changelog/internet lookup, you should normally route to research before senior_staff_engineer, architect, or coder.
- You may skip research only with an explicit waiver: policy_evaluation.can_skip_research=true, a non-empty skip_research_reason, and accepted_report_ids.scout pointing to the Scout report you relied on. Use this only when the Scout research domains are irrelevant, already answered by local evidence, or the task is too small/risky to delay.
- Prefer senior_staff_engineer before architect when execution environment assumptions or high-level risks exist.
- Architect is normally required before coder. You may skip architect only with an explicit waiver: policy_evaluation.can_skip_architect=true, a non-empty skip_architect_reason, accepted_report_ids.senior_staff_engineer, and a senior staff report with exact fix_scope/files_to_change/validation_strategy that you accept as sufficient for this low-risk implementation. For multi-file design, public API, workflow, dependency, schema/proto, CI/runtime, or uncertain changes, route to architect instead.
- After coder returns PASS/ready, normally choose RUN_ROLE qa before reviewer.
- After QA returns PASS, inspect QA typed report: validation targets, commands, environment reconstruction, gaps, skipped/not_run targets, validation_level, qa_recommendation, and compare validation.targets to validation_profile.required_targets. Decide whether gaps are blocking, accepted risk, or require QA retry/coder retry/ASK_HUMAN.
- QA action=PASS is only QA's recommendation. Do not automatically accept it. Reject QA PASS for review/publish when required runtime/smoke/integration/CI targets were skipped, not_run, syntax-only, not executed end-to-end, or skipped gracefully without the required live server/runtime.
- For CI failure, runtime bug, integration bug, smoke test, GUI/Xvfb, gRPC/server, or end-to-end workflow tasks, validation_level=targeted_unit is insufficient unless the failed/requested target was explicitly unit-only. If QA only ran unit tests while runtime/smoke/integration tests were skipped, choose RETRY_ROLE qa with setup instructions or ASK_HUMAN after real setup attempts fail.
- Skipped tests are not passing tests. Phrases like "integration tests skipped gracefully", "smoke test not executed end-to-end", "requires Freeplane/Xvfb/Java runtime not available", "without server", or "verify in CI" are blocking QA evidence unless QA documented concrete setup attempts and you explicitly accept the risk for a non-runtime task.
- When rejecting QA PASS, set policy_evaluation.can_review=false, qa_evidence_accepted=false, put the exact rejected gaps in blocking_reasons, and route to QA with instructions to install/setup/start the missing runtime or service using repository scripts/CI workflow.
- After reviewer returns PASS, inspect reviewer typed report: diff review, QA evidence review, lint/static checks, findings, required_fixes, publisher_ready, and validation_review. Decide whether publishing is safe.
- Do not choose publisher until you explicitly accept both QA and reviewer evidence in policy_evaluation and set policy_evaluation.can_publish=true.
- If QA returned NEED_FIX or BLOCKER caused by implementation/validation failure, choose RETRY_ROLE coder with concrete QA feedback or ASK_HUMAN if unsafe.
- If reviewer returned NEED_FIX, choose RETRY_ROLE coder with concrete reviewer feedback.
- After publisher returns, inspect the publisher typed report: publish.pr_url, publish.head_sha, and pr_checks. Publisher PASS is not acceptable without structured pr_checks evidence that gh discovered PR checks/statuses, waited for them, and they completed successfully.
- If publisher created a PR but did not report pr_checks, did not wait for checks, reported no_checks_found/timed_out/pending/failing checks, or only summarized PR creation, choose RETRY_ROLE publisher with instructions to use gh pr view and gh pr checks --watch/--json, not STOP_COMPLETED.
- If PR checks/statuses completed successfully and you accept the publisher report, choose STOP_COMPLETED with policy_evaluation.can_complete=true and publisher_pr_checks_accepted=true. If checks failed, cancelled, timed out, or publisher returned NEED_FIX/BLOCKER, treat PR checks as a new feedback loop: usually route to scout for facts-only CI log collection if the failing check/logs are not already collected, then research/senior_staff/architect/coder as needed. Choose publisher retry only for GitHub/gh/check discovery issues, not for code/test failures.
- If max steps is reached or the next safe role is unclear, choose ASK_HUMAN.

Policy evaluation guidance:
- For research skipping, set policy_evaluation.can_skip_research=true only if you deliberately accept skipping Research despite Scout research_required/research_domains; include skip_research_reason and accepted_report_ids.scout.
- For architect skipping, set policy_evaluation.can_skip_architect=true only if you deliberately accept Senior Staff's exact low-risk fix scope as sufficient implementation plan; include skip_architect_reason and accepted_report_ids.senior_staff_engineer.
- For reviewer routing, set policy_evaluation.can_review=true only if you accepted the latest QA result as sufficient for review. QA PASS includes build/test validation evidence, typed validation targets, gaps, skipped/not_run targets, and recommendation fields that you must evaluate. Do not set can_review=true when required integration/smoke/runtime targets were skipped or only unit validation ran for a runtime/CI task.
- For publisher routing, set policy_evaluation.can_publish=true only if you accepted the latest QA result and latest reviewer result as sufficient for publication.
- For STOP_COMPLETED after publisher, set policy_evaluation.can_complete=true and publisher_pr_checks_accepted=true only if you accepted the publisher PR URL/head SHA and the reported PR checks/statuses as completed successfully. Do not complete on PR creation alone.
- Put rejected/accepted gaps in policy_evaluation.blocking_reasons and policy_evaluation.accepted_risks. Treat QA statements such as "out of scope" and publisher PR check failures/timeouts as evidence to evaluate, not as a LangGraph hardcode.
- Include accepted_report_ids for every report you relied on: coder, qa, reviewer, etc. Use report_id values from Workflow history when present.

Decision output requirements:
Your normal answer must be concise and explain only the next decision. The summary JSON for this role must contain all routing fields listed in the summary instruction.

When choosing RUN_ROLE/RETRY_ROLE, include:
- next_role
- role_instance
- context_sources
- instructions
- reason

Recommended role_instance names:
- scout-1, research-1, senior_staff_engineer-1, architect-1, coder-1, qa-1, reviewer-1, publisher-1

Final line:
TEAM_LEAD_STATUS: COMPLETE
""".strip()



def build_team_lead_decision_prompt(state: JsonDict) -> str:
    """Prompt for direct tool-less Team Lead LLM calls.

    Unlike build_team_lead_prompt(), this is consumed directly by an
    OpenAI-compatible chat completion and must request the final routing JSON
    directly. There is no OpenHands answer and no summary pass for Team Lead.
    """
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
        "scout": '''FINAL_ROLE_REPORT_JSON:
{
  "schema_version": "1.0",
  "role": "scout",
  "action": "PASS",
  "summary": "facts-only context collected",
  "risk_level": "medium",
  "blocking": false,
  "blocking_summary": [],
  "research_required": true,
  "research_domains": [],
  "research_questions": [],
  "unknowns": [],
  "validation_questions": [],
  "routing_hints": {"recommended_next_role": "research", "reason": "external dependency/runtime questions remain"},
  "validation_profile": {"profile_id": "validation-profile-1", "ci_workflows": [], "required_targets": [{"name": "integration", "required": true, "required_by": "ci", "category": "integration", "commands": [], "environment": [], "setup": [], "env": [], "source": "ci"}], "runtime_services": [], "startup_scripts": [], "required_env": [], "notes": []},
  "facts": {
    "ci_failure": {"job": "", "step": "", "command": "", "error": "", "failing_tests": []},
    "relevant_files": [],
    "documented_commands": [],
    "research_domains": [],
    "research_questions": [],
    "unknowns": [],
    "validation_questions": []
  }
}
Do not include root_cause, hypothesis, candidate_causes, or diagnosis fields.''',
        "senior_staff_engineer": '''FINAL_ROLE_REPORT_JSON:
{
  "schema_version": "1.0",
  "role": "senior_staff_engineer",
  "action": "PASS",
  "summary": "strategy completed",
  "risk_level": "medium",
  "blocking": false,
  "blocking_summary": [],
  "root_cause": "",
  "fix_scope": "",
  "files_to_change": [],
  "files_inspected": [],
  "validation_strategy": "",
  "confidence": "medium",
  "architect_waiver_candidate": false,
  "target_runtime_contract": {},
  "validation_profile": {"profile_id": "validation-profile-1", "required_targets": [], "runtime_services": [], "startup_scripts": [], "required_env": []},
  "assumption_ledger": [],
  "strategy": {"recommended_next_role": "architect", "reason": ""},
  "routing_hints": {"architect_required": true, "coder_direct_allowed_candidate": false, "reason": ""}
}''',
        "coder": '''FINAL_ROLE_REPORT_JSON:
{
  "schema_version": "1.0",
  "role": "coder",
  "action": "PASS",
  "summary": "implementation completed",
  "risk_level": "medium",
  "blocking": false,
  "blocking_summary": [],
  "change_set_id": "coder-1-attempt-1",
  "files_changed": [],
  "implementation": {"summary": "", "deviations_from_plan": [], "known_issues": []},
  "self_validation": {"build_commands": [], "test_commands": [], "passed": false, "gaps": []},
  "ready_for_qa": true
}''',
        "qa": '''FINAL_ROLE_REPORT_JSON:
{
  "schema_version": "1.0",
  "role": "qa",
  "action": "PASS",
  "summary": "validation completed",
  "risk_level": "low",
  "blocking": false,
  "blocking_summary": [],
  "validated_change_set_id": "coder-1-attempt-1",
  "validation_profile": {"profile_id": "validation-profile-1", "required_targets": [], "runtime_services": [], "startup_scripts": [], "required_env": []},
  "validation": {
    "overall_status": "passed",
    "validation_level": "targeted_integration",
    "environment_reconstructed": true,
    "repository_scripts_used": true,
    "targets": [
      {"name": "java_compile", "required": true, "required_by": "build", "status": "passed", "commands": [], "evidence": "", "setup_attempted": true, "profile_target_matched": true},
      {"name": "python_smoke_tests", "required": true, "required_by": "ci", "status": "passed", "commands": [], "evidence": "", "setup_attempted": true}
    ],
    "gaps": [
      {"target": "", "blocking_candidate": false, "reason": "", "setup_attempted": true, "message": ""}
    ],
    "build_ran": true,
    "build_passed": true,
    "tests_run": true,
    "tests_passed": true,
    "build_commands": [],
    "test_commands": [],
    "setup_commands": [],
    "install_commands": []
  },
  "required_targets_passed": true,
  "blocking_gaps": [],
  "accepted_gaps": [],
  "qa_recommendation": {"ready_for_review": true, "recommended_next_role": "reviewer", "reason": ""},
  "ready_for_review": true
}''',
        "reviewer": '''FINAL_ROLE_REPORT_JSON:
{
  "schema_version": "1.0",
  "role": "reviewer",
  "action": "PASS",
  "summary": "review passed",
  "risk_level": "medium",
  "blocking": false,
  "blocking_summary": [],
  "reviewed_change_set_id": "coder-1-attempt-1",
  "reviewed_qa_report_id": "qa-1-attempt-1",
  "review": {
    "diff_reviewed": true,
    "qa_evidence_reviewed": true,
    "qa_evidence_accepted": true,
    "lint_static_checks": [],
    "findings": [],
    "required_fixes": [],
    "publisher_ready": true
  },
  "validation_review": {
    "qa_build_evidence_ok": true,
    "qa_test_evidence_ok": true,
    "qa_validation_level_ok": true,
    "environment_reconstruction_reviewed": true,
    "syntax_only_rejected": true,
    "lint_commands": [],
    "setup_commands_reviewed": [],
    "validation_gaps": []
  }
}''',
        "publisher": '''FINAL_ROLE_REPORT_JSON:
{
  "schema_version": "1.0",
  "role": "publisher",
  "action": "PASS",
  "summary": "PR created and PR checks passed",
  "risk_level": "low",
  "blocking": false,
  "blocking_summary": [],
  "published_change_set_id": "coder-1-attempt-1",
  "publish": {"branch": "feature/example", "commit": "", "head_sha": "", "base": "main", "pr_number": 0, "pr_url": "", "pushed": true, "pr_created": true, "existing_pr": false},
  "pr_checks": {
    "overall_status": "passed",
    "head_sha": "",
    "waited": true,
    "timeout_seconds": 1800,
    "poll_interval_seconds": 30,
    "check_runs": [{"name": "ci", "status": "completed", "conclusion": "success", "url": ""}],
    "commit_status": {"state": "success", "statuses": []},
    "failing_checks": [],
    "pending_checks": [],
    "checked_at": ""
  },
  "pr_feedback": {"failed_check_logs_collected": false, "failure_summary": "", "failing_steps": [], "log_urls": []},
  "publisher_recommendation": {"ready_to_complete": true, "recommended_next_role": "team_lead", "reason": "PR checks passed"}
}''',
    }
    default = f'''FINAL_ROLE_REPORT_JSON:
{{"schema_version": "1.0", "role": "{role}", "action": "PASS", "summary": "", "risk_level": "medium", "blocking": false, "blocking_summary": []}}'''
    example = examples.get(role, default)
    return f'''Structured report requirement:
At the end of your answer, include exactly one machine-readable footer named FINAL_ROLE_REPORT_JSON.
This footer is used by Team Lead for policy decisions. Do not rely on prose only.
The JSON must be valid, compact enough to parse, and must reflect what you actually did.
Common required keys: schema_version, role, action, summary, risk_level, blocking, blocking_summary.

Example shape:
{example}'''.strip()


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
    return f"""Return ONE compact valid JSON object only. No Markdown, no code fence, no prose before/after JSON.
Required keys: valid, status, summary, action, risk_level, blocking, blocking_summary.
Allowed risk_level values: low, medium, high, critical, null.
The summary string must be concise, preferably under 900 characters. Escape all quotes correctly.
Set blocking=true only for real blockers and put blocker details in blocking_summary.
{guidance}
Example shape:
{{"valid": true, "status": "completed", "summary": "...", "action": "PASS", "risk_level": "low", "blocking": false, "blocking_summary": []}}"""


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
            "QA action must be PASS only when compilation/build and targeted test/smoke/integration validation actually ran and passed in a credible validation environment. NEED_FIX when coder/test-harness changes are required, or BLOCKER when validation cannot proceed after package/setup/environment reconstruction attempts. Include extra key validation with build_ran, build_passed, tests_run, tests_passed, validation_level, install_commands, setup_commands, build_commands, test_commands, targets, gaps, and validation_gaps. Copy the validation object from the QA answer into this summary JSON exactly; do not omit it. validation_level must be one of ci_like, targeted_runtime, targeted_integration, targeted_unit, syntax_only, not_validated. PASS requires build_ran/build_passed/tests_run/tests_passed all true, non-empty build_commands/test_commands, validation_level not syntax_only/not_validated, every required target passed, and no required CI/runtime/smoke/integration target skipped/not_run/excluded or merely syntax-checked.",
        )
    if role == "reviewer":
        return _summary_schema_contract(
            role,
            "Reviewer action must be PASS, NEED_FIX, or BLOCKER. PASS requires QA PASS with build/test validation evidence, validation_level not syntax_only/not_validated, no required environment/setup gaps, plus independent code/diff review and relevant lint/static checks for changed file types when practical. Include extra key validation_review with qa_build_evidence_ok, qa_test_evidence_ok, qa_validation_level_ok, environment_reconstruction_reviewed, syntax_only_rejected, lint_commands, setup_commands_reviewed, validation_gaps. Copy the validation_review object from the reviewer answer into this summary JSON exactly; do not omit it. If QA skipped relevant runtime/integration/smoke tests as out-of-scope or downgraded to syntax-only because an upstream/core repository was missing, Reviewer must not PASS.",
        )
    if role == "publisher":
        return _summary_schema_contract(
            role,
            "Publisher action must be PASS only when a PR was created/found, the pushed branch/head SHA was identified, GitHub PR checks/statuses were discovered with gh, waited for with gh pr checks --watch or an equivalent bounded gh polling loop, completed successfully, and publishing is ready for Team Lead to stop. Use NEED_FIX when PR checks/statuses fail, are cancelled, remain pending at timeout, no checks are found at timeout, or indicate code/test changes are required. Use BLOCKER when publishing/check discovery cannot proceed because of GitHub/GITHUB_TOKEN/gh/push blockers. Include extra key pr_checks with overall_status, head_sha, waited, timeout_seconds, poll_interval_seconds, check_runs, commit_status, failing_checks, pending_checks, and checked_at. Copy the pr_checks object from the publisher answer into summary JSON exactly; do not omit it. PASS is invalid without pr_checks.",
        )
    if role == "coder":
        return _summary_schema_contract(
            role,
            "Use PASS only if implementation is ready for QA with compilation/build and targeted validation evidence, NEED_FIX if validation failed due to the change, or BLOCKER if implementation could not proceed. Include install commands, compile/build/test status, validation gaps, and remaining known issues.",
        )
    if role == "senior_staff_engineer":
        return _summary_schema_contract(
            role,
            "Senior Staff action must be PASS/PROCEED when the execution contract is ready for Architect, NEED_FIX/NEED_MORE_RESEARCH/NEED_MORE_SCOUT/ASK_HUMAN when more input is required, or BLOCKER when proceeding is unsafe. Include structured fields when available: root_cause, fix_scope, files_to_change, files_inspected, validation_strategy, confidence, architect_waiver_candidate, routing_hints, target_runtime_contract, assumption_ledger. Do not recommend direct coder unless the fix scope is explicit, low risk, and validation strategy is clear; mark architect_waiver_candidate accordingly.",
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
    """Human-readable summary of what will be passed into a role.

    This is used for colored CLI tracing. It intentionally does not expose the
    full prompt or full upstream answers.
    """
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
        if _summary_text(scout):
            lines.append(f"scout routing summary: {_short(_summary_text(scout), 220)}")
        lines.append(f"research brief artifact: {_answer_len(research)} chars")
        if _summary_text(research):
            lines.append(f"research routing summary: {_short(_summary_text(research), 220)}")
        lines.append("mode: senior strategy gate; execution contract + assumption ledger; no commands/installers")
    elif role == "architect":
        scout = state.get("scout_result")
        research = state.get("research_result")
        senior = state.get("senior_staff_engineer_result")
        lines.append(f"scout answer artifact: {_answer_len(scout)} chars")
        if _summary_text(scout):
            lines.append(f"scout routing summary: {_short(_summary_text(scout), 220)}")
        lines.append(f"research brief artifact: {_answer_len(research)} chars")
        if _summary_text(research):
            lines.append(f"research routing summary: {_short(_summary_text(research), 220)}")
        lines.append(f"senior staff strategy artifact: {_answer_len(senior)} chars")
        if _summary_text(senior):
            lines.append(f"senior staff routing summary: {_short(_summary_text(senior), 220)}")
        lines.append("mode: read-only planning; tests/builds/installers forbidden")
    elif role == "coder":
        senior = state.get("senior_staff_engineer_result")
        architect = state.get("architect_result")
        reviewer = state.get("reviewer_result") if state.get("current_iteration", 0) else None
        lines.append(f"senior staff strategy artifact: {_answer_len(senior)} chars")
        if _summary_text(senior):
            lines.append(f"senior staff routing summary: {_short(_summary_text(senior), 220)}")
        lines.append(f"architect plan artifact: {_answer_len(architect)} chars")
        if _summary_text(architect):
            lines.append(f"architect routing summary: {_short(_summary_text(architect), 220)}")
        if reviewer:
            lines.append(f"reviewer feedback artifact: {_answer_len(reviewer)} chars")
            if _summary_text(reviewer):
                lines.append(f"reviewer routing summary: {_short(_summary_text(reviewer), 220)}")
        lines.append(f"iteration: {int(state.get('current_iteration') or 0) + 1}")
        lines.append("mode: implementation/validation in Debian Trixie Docker sandbox; install packages with sudo when needed")
    elif role == "qa":
        senior = state.get("senior_staff_engineer_result")
        architect = state.get("architect_result")
        coder = state.get("coder_result")
        lines.append(f"senior staff strategy artifact: {_answer_len(senior)} chars")
        if _summary_text(senior):
            lines.append(f"senior staff routing summary: {_short(_summary_text(senior), 220)}")
        lines.append(f"architect plan artifact: {_answer_len(architect)} chars")
        if _summary_text(architect):
            lines.append(f"architect routing summary: {_short(_summary_text(architect), 220)}")
        if _summary_text(coder):
            lines.append(f"coder routing summary only: {_short(_summary_text(coder), 220)}")
        lines.append("mode: QA validation; install required utilities with sudo; compile/build and run targeted tests")
    elif role == "reviewer":
        senior = state.get("senior_staff_engineer_result")
        architect = state.get("architect_result")
        coder = state.get("coder_result")
        lines.append(f"senior staff strategy artifact: {_answer_len(senior)} chars")
        if _summary_text(senior):
            lines.append(f"senior staff routing summary: {_short(_summary_text(senior), 220)}")
        lines.append(f"architect plan artifact: {_answer_len(architect)} chars")
        if _summary_text(coder):
            lines.append(f"coder routing summary only: {_short(_summary_text(coder), 220)}")
        qa = state.get("qa_result")
        lines.append(f"qa validation artifact: {_answer_len(qa)} chars")
        if _summary_text(qa):
            lines.append(f"qa routing summary: {_short(_summary_text(qa), 220)}")
        lines.append("mode: independent review after QA; install required linters/checkers with sudo; do not modify implementation files")
    elif role == "publisher":
        senior = state.get("senior_staff_engineer_result")
        architect = state.get("architect_result")
        reviewer = state.get("reviewer_result")
        lines.append(f"senior staff strategy artifact: {_answer_len(senior)} chars")
        if _summary_text(senior):
            lines.append(f"senior staff routing summary: {_short(_summary_text(senior), 220)}")
        lines.append(f"architect plan artifact: {_answer_len(architect)} chars")
        qa = state.get("qa_result")
        if _summary_text(qa):
            lines.append(f"qa routing summary: {_short(_summary_text(qa), 220)}")
        if _summary_text(reviewer):
            lines.append(f"reviewer routing summary: {_short(_summary_text(reviewer), 220)}")
        lines.append("mode: inspect changes, push branch, create PR with gh + GITHUB_TOKEN, wait for PR checks/statuses; sudo allowed for missing publishing tools")
    else:
        lines.append("custom role prompt is passed as-is")
    return lines
