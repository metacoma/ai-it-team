from __future__ import annotations

from typing import Any

import pytest

from openhands import OpenHandsRoleRunner
from openhands.models import AppConversationStart, OpenHandsRunResult, RoleRunResult, RoleSummary
from openhands_langgraph import build_development_graph
from openhands_langgraph.prompts import (
    build_architect_prompt,
    build_coder_prompt,
    build_publisher_prompt,
    build_qa_prompt,
    build_research_prompt,
    build_reviewer_prompt,
    build_scout_prompt,
    build_senior_staff_engineer_prompt,
    build_team_lead_prompt,
)


class FakeDevelopmentRunner(OpenHandsRoleRunner):
    def __init__(self, reviewer_actions: list[str], senior_staff_action: str = "PROCEED") -> None:
        self.reviewer_actions = list(reviewer_actions)
        self.senior_staff_action = senior_staff_action
        self.calls: list[dict[str, Any]] = []
        self._conversation_counter = 0
        self._reviewer_counter = 0

    async def run_role(self, **kwargs: Any) -> RoleRunResult:  # type: ignore[override]
        self.calls.append(kwargs)
        self._conversation_counter += 1
        role = kwargs.get("role") or "role"
        action = {
            "scout": "CONTINUE",
            "research": "PASS",
            "senior_staff_engineer": self.senior_staff_action,
            "architect": "PLAN_READY",
            "coder": "COMPLETED",
            "qa": "PASS",
            "publisher": "PASS",
        }.get(role, "PASS")
        if role == "reviewer":
            idx = min(self._reviewer_counter, len(self.reviewer_actions) - 1)
            action = self.reviewer_actions[idx]
            self._reviewer_counter += 1

        blocking = action == "BLOCKER"
        status = "blocked" if blocking else ("needs_fix" if action in {"NEED_FIX", "NEED_MORE_RESEARCH", "NEED_MORE_SCOUT", "ASK_HUMAN"} else "completed")
        conversation_id = f"conv-{self._conversation_counter}"
        start = AppConversationStart(conversation_id=conversation_id, status="READY")
        answer_run = OpenHandsRunResult(
            text=f"{role} answer {self._conversation_counter}",
            status="finished",
            conversation_id=conversation_id,
            start=start,
        )
        summary_kwargs = {}
        if role == "qa" and action == "PASS":
            summary_kwargs["validation"] = {
                "build_ran": True,
                "build_passed": True,
                "tests_run": True,
                "tests_passed": True,
                "validation_level": "targeted_runtime",
                "install_commands": ["sudo apt-get install -y test-tool"],
                "setup_commands": ["prepare documented validation layout"],
                "build_commands": ["./gradlew compileJava"],
                "test_commands": ["pytest smoke.py"],
                "validation_gaps": [],
            }
        if role == "reviewer" and action == "PASS":
            summary_kwargs["validation_review"] = {
                "qa_build_evidence_ok": True,
                "qa_test_evidence_ok": True,
                "qa_validation_level_ok": True,
                "environment_reconstruction_reviewed": True,
                "syntax_only_rejected": True,
                "lint_commands": ["python -m py_compile example.py"],
                "setup_commands_reviewed": ["prepare documented validation layout"],
                "validation_gaps": [],
            }
        summary = RoleSummary(
            valid=True,
            status=status,
            summary=f"{role} summary",
            action=action,
            risk_level="low" if not blocking else "high",
            blocking=blocking,
            blocking_summary=["blocked by test"] if blocking else [],
            **summary_kwargs,
        )
        return RoleRunResult(
            role=role,
            role_instance=kwargs.get("role_instance"),
            answer=answer_run.text,
            summary_text=summary.model_dump_json(),
            summary_json=summary,
            answer_run=answer_run,
            summary_attempts=[],
        )


@pytest.mark.parametrize(
    "builder",
    [
        build_scout_prompt,
        build_research_prompt,
        build_senior_staff_engineer_prompt,
        build_architect_prompt,
        build_coder_prompt,
        build_qa_prompt,
        build_reviewer_prompt,
        build_publisher_prompt,
    ],
)
def test_development_prompts_are_role_specific_and_do_not_force_repository_path(builder) -> None:
    prompt = builder(
        {
            "user_task": "добавь Ruby gRPC client",
            "repository": "metacoma/freeplane_plugin_grpc",
        }
    )

    assert "Original user task" in prompt
    assert "metacoma/freeplane_plugin_grpc" in prompt
    assert "Do not" in prompt
    assert "Output" in prompt
    assert "/workspace/git" not in prompt
    assert "fixed checkout directory" in prompt or "hard-coded checkout path" in prompt or "hardcoded" in prompt.lower()


def test_development_prompts_work_without_repository() -> None:
    prompt = build_scout_prompt({"user_task": "inspect current OpenHands workspace"})

    assert "No repository was specified in graph state" in prompt
    assert "/workspace/git" not in prompt
    assert "do not assume" in prompt.lower()


def test_scout_architect_and_senior_staff_prompts_forbid_validation_execution() -> None:
    scout_prompt = build_scout_prompt({"user_task": "inspect repo"})
    senior_prompt = build_senior_staff_engineer_prompt(
        {
            "user_task": "strategy",
            "scout_result": {"role": "scout", "ok": True, "summary": {"summary": "scout"}, "answer": "scout report"},
            "research_result": {"role": "research", "ok": True, "summary": {"summary": "research"}, "answer": "research brief"},
        }
    )
    architect_prompt = build_architect_prompt(
        {
            "user_task": "plan change",
            "scout_result": {"role": "scout", "ok": True, "summary": {"summary": "scout summary"}, "answer": "scout report"},
            "research_result": {"role": "research", "ok": True, "summary": {"summary": "research summary"}, "answer": "research brief"},
            "senior_staff_engineer_result": {"role": "senior_staff_engineer", "ok": True, "summary": {"summary": "strategy"}, "answer": "execution contract"},
        }
    )

    for prompt in [scout_prompt, senior_prompt, architect_prompt]:
        lowered = prompt.lower()
        assert "must not run tests" in lowered
        assert "must not run sudo" in lowered
        assert "pytest" in lowered
        assert "gradle build" in lowered
        assert "without executing them" in lowered or "you must not execute them" in lowered


def test_scout_requests_research_domains_and_research_prompt_consumes_them() -> None:
    scout_prompt = build_scout_prompt({"user_task": "add GitHub Actions smoke tests"})
    assert "Research Domains For Research Role" in scout_prompt
    assert "target runtime/environment domains" in scout_prompt

    research_prompt = build_research_prompt(
        {
            "user_task": "add GitHub Actions smoke tests",
            "scout_result": {
                "role": "scout",
                "ok": True,
                "summary": {"summary": "scout found CI/runtime domains"},
                "answer": "# Scout Report\n## Research Domains For Research Role\n- domain: CI provider",
            },
        }
    )
    assert "Research / External Best-Practices Investigator" in research_prompt
    assert "External Environment Contracts" in research_prompt
    assert "CI provider" in research_prompt


def test_senior_staff_prompt_builds_execution_contract_from_scout_and_research() -> None:
    prompt = build_senior_staff_engineer_prompt(
        {
            "user_task": "add integration tests",
            "scout_result": {"role": "scout", "ok": True, "summary": {"summary": "scout summary"}, "answer": "FULL SCOUT REPORT: target runtime may be external CI"},
            "research_result": {"role": "research", "ok": True, "summary": {"summary": "research summary"}, "answer": "FULL RESEARCH BRIEF: external runtime constraints"},
        }
    )
    assert "Senior Staff Engineer / Execution Strategy Gate" in prompt
    assert "Target Runtime Contract" in prompt
    assert "Assumption Ledger" in prompt
    assert "Cheap Preflight Checks" in prompt
    assert "FULL SCOUT REPORT" in prompt
    assert "FULL RESEARCH BRIEF" in prompt
    assert "MUST NOT run sudo" in prompt or "must not run sudo" in prompt.lower()


def test_mutable_environment_rules_are_only_in_executor_like_roles() -> None:
    state = {
        "user_task": "implement feature",
        "senior_staff_engineer_result": {"role": "senior_staff_engineer", "summary": {"summary": "strategy"}, "answer": "strategy"},
        "architect_result": {"role": "architect", "summary": {"summary": "plan"}, "answer": "plan"},
        "coder_result": {"role": "coder", "summary": {"summary": "coder summary"}, "answer": "coder report"},
        "qa_result": {"role": "qa", "summary": {"summary": "qa summary", "action": "PASS"}, "answer": "QA validation passed"},
        "reviewer_result": {"role": "reviewer", "summary": {"summary": "reviewer summary", "action": "PASS"}},
    }
    for prompt in [build_coder_prompt(state), build_qa_prompt(state), build_reviewer_prompt(state), build_publisher_prompt(state)]:
        assert "Docker sandbox based on Debian Trixie" in prompt
        assert "use sudo" in prompt
        assert "sudo apt-get update" in prompt

    for prompt in [build_scout_prompt(state), build_research_prompt(state), build_senior_staff_engineer_prompt(state), build_architect_prompt(state)]:
        assert "Docker sandbox based on Debian Trixie" not in prompt
        assert "must not run sudo" in prompt.lower() or "do not" in prompt.lower()


def test_role_input_summary_is_short_and_never_contains_full_prompt() -> None:
    from openhands_langgraph.prompts import role_input_summary

    state = {
        "user_task": "implement feature",
        "scout_result": {"role": "scout", "ok": True, "summary": {"summary": "short scout summary"}, "answer": "X" * 5000},
    }

    lines = role_input_summary("architect", state)

    assert any("scout answer artifact: 5000 chars" in line for line in lines)
    assert all("X" * 100 not in line for line in lines)


def _state_with_all_upstream() -> dict[str, Any]:
    return {
        "user_task": "implement feature",
        "scout_result": {
            "role": "scout",
            "conversation_id": "conv-scout",
            "ok": True,
            "summary_action": "CONTINUE",
            "summary": {"summary": "short scout summary"},
            "answer": "FULL SCOUT REPORT: file map and validation commands",
        },
        "research_result": {
            "role": "research",
            "conversation_id": "conv-research",
            "ok": True,
            "summary_action": "PASS",
            "summary": {"summary": "short research summary"},
            "answer": "FULL RESEARCH BRIEF: target runtime contract",
        },
        "senior_staff_engineer_result": {
            "role": "senior_staff_engineer",
            "conversation_id": "conv-senior",
            "ok": True,
            "summary_action": "PROCEED",
            "summary": {"summary": "short senior staff summary"},
            "answer": "FULL SENIOR STAFF STRATEGY: execution contract and assumptions",
        },
        "architect_result": {
            "role": "architect",
            "conversation_id": "conv-architect",
            "ok": True,
            "summary_action": "PLAN_READY",
            "summary": {"summary": "short architect summary"},
            "answer": "FULL ARCHITECT PLAN: exact implementation steps",
        },
        "coder_result": {
            "role": "coder",
            "conversation_id": "conv-coder",
            "ok": True,
            "summary_action": "COMPLETED",
            "summary": {"summary": "short coder summary"},
            "answer": "FULL CODER REPORT: files changed and tests run",
        },
        "role_results": [],
    }


def test_downstream_prompts_include_full_upstream_answers() -> None:
    state = _state_with_all_upstream()

    architect_prompt = build_architect_prompt(state)
    coder_prompt = build_coder_prompt(state)
    qa_prompt = build_qa_prompt(state)
    reviewer_prompt = build_reviewer_prompt(state)

    assert "FULL SCOUT REPORT" in architect_prompt
    assert "FULL RESEARCH BRIEF" in architect_prompt
    assert "FULL SENIOR STAFF STRATEGY" in architect_prompt
    assert "FULL SENIOR STAFF STRATEGY" in coder_prompt
    assert "FULL ARCHITECT PLAN" in coder_prompt
    assert "FULL SENIOR STAFF STRATEGY" in qa_prompt
    assert "FULL ARCHITECT PLAN" in qa_prompt
    assert "short coder summary" in qa_prompt
    assert "FULL CODER REPORT" not in qa_prompt
    assert "FULL SENIOR STAFF STRATEGY" in reviewer_prompt
    assert "FULL ARCHITECT PLAN" in reviewer_prompt
    assert "FULL CODER REPORT" not in reviewer_prompt
    assert "short coder summary" in reviewer_prompt
    assert "coder summary" in reviewer_prompt.lower()
    assert "not evidence" in reviewer_prompt
    assert "QA validation" in reviewer_prompt or "QA Evidence" in reviewer_prompt

    publisher_prompt = build_publisher_prompt({**state, "qa_result": {"summary": {"summary": "qa PASS summary", "action": "PASS"}}, "reviewer_result": {"summary": {"summary": "reviewer PASS summary", "action": "PASS"}}})
    assert "FULL SENIOR STAFF STRATEGY" in publisher_prompt
    assert "FULL ARCHITECT PLAN" in publisher_prompt
    assert "qa PASS summary" in publisher_prompt
    assert "reviewer PASS summary" in publisher_prompt
    assert "GITHUB_TOKEN" in publisher_prompt
    assert "gh" in publisher_prompt


def test_downstream_prompts_do_not_embed_full_role_result_json_or_duplicate_summaries() -> None:
    state = {
        "user_task": "validate ruby grpc integration tests",
        "scout_result": {
            "role": "scout",
            "role_instance": "scout-1",
            "conversation_id": "conv-scout",
            "ok": True,
            "summary_action": "PASS",
            "risk_level": "low",
            "blocking": False,
            "summary": {"valid": True, "status": "completed", "action": "PASS", "risk_level": "low", "blocking": False, "summary": "Scout summary only once"},
            "answer": "# Scout Report\nFull scout markdown artifact",
        },
        "research_result": {
            "role": "research",
            "role_instance": "research-1",
            "conversation_id": "conv-research",
            "ok": True,
            "summary_action": "PASS",
            "risk_level": "low",
            "blocking": False,
            "summary": {"valid": True, "status": "completed", "action": "PASS", "risk_level": "low", "blocking": False, "summary": "Research summary only once"},
            "answer": "# Research Brief\nFull research markdown artifact",
        },
        "senior_staff_engineer_result": {
            "role": "senior_staff_engineer",
            "role_instance": "senior_staff_engineer-1",
            "conversation_id": "conv-senior",
            "ok": True,
            "summary_action": "PROCEED",
            "risk_level": "low",
            "blocking": False,
            "summary": {"valid": True, "status": "completed", "action": "PROCEED", "risk_level": "low", "blocking": False, "summary": "Senior staff summary only once"},
            "answer": "# Senior Staff Strategy\nFull senior staff markdown artifact",
        },
        "architect_result": {
            "role": "architect",
            "role_instance": "architect-1",
            "conversation_id": "conv-architect",
            "ok": True,
            "summary_action": "PASS",
            "risk_level": "low",
            "blocking": False,
            "summary": {"valid": True, "status": "completed", "action": "PASS", "risk_level": "low", "blocking": False, "summary": "Architect summary only once"},
            "answer": "# Architect Plan\nFull architect markdown artifact",
        },
        "coder_result": {
            "role": "coder",
            "role_instance": "coder-1",
            "conversation_id": "conv-coder",
            "ok": True,
            "summary_action": "PASS",
            "risk_level": "low",
            "blocking": False,
            "summary": {"valid": True, "status": "completed", "action": "PASS", "risk_level": "low", "blocking": False, "summary": "Coder summary only once"},
            "answer": "# Coder Report\nFull coder markdown artifact",
        },

        "qa_result": {
            "role": "qa",
            "role_instance": "qa-1",
            "conversation_id": "conv-qa",
            "ok": True,
            "summary_action": "PASS",
            "risk_level": "low",
            "blocking": False,
            "summary": {"valid": True, "status": "completed", "action": "PASS", "risk_level": "low", "blocking": False, "summary": "QA summary only once"},
            "answer": "# QA Report\nFull QA validation markdown artifact",
        },
        "role_results": [],
    }

    architect_prompt = build_architect_prompt(state)
    coder_prompt = build_coder_prompt(state)
    qa_prompt = build_qa_prompt(state)
    reviewer_prompt = build_reviewer_prompt(state)

    assert "----- BEGIN SCOUT REPORT ANSWER -----" in architect_prompt
    assert "Full scout markdown artifact" in architect_prompt
    assert "----- BEGIN RESEARCH BRIEF ANSWER -----" in architect_prompt
    assert "Full research markdown artifact" in architect_prompt
    assert "----- BEGIN SENIOR STAFF STRATEGY ANSWER -----" in architect_prompt
    assert "Full senior staff markdown artifact" in architect_prompt
    assert '"answer"' not in architect_prompt
    assert '"summary_action"' not in architect_prompt
    assert "Previous role summaries" not in architect_prompt
    assert architect_prompt.count("Scout summary only once") == 1
    assert architect_prompt.count("Research summary only once") == 1
    assert architect_prompt.count("Senior staff summary only once") == 1

    assert "----- BEGIN SENIOR STAFF STRATEGY ANSWER -----" in coder_prompt
    assert "Full senior staff markdown artifact" in coder_prompt
    assert "----- BEGIN ARCHITECT PLAN ANSWER -----" in coder_prompt
    assert "Full architect markdown artifact" in coder_prompt
    assert '"answer"' not in coder_prompt
    assert '"summary_action"' not in coder_prompt
    assert "Previous role summaries" not in coder_prompt
    assert coder_prompt.count("Architect summary only once") == 1
    assert coder_prompt.count("Senior staff summary only once") == 1

    assert "----- BEGIN SENIOR STAFF STRATEGY ANSWER -----" in qa_prompt
    assert "----- BEGIN ARCHITECT PLAN ANSWER -----" in qa_prompt
    assert "Full coder markdown artifact" not in qa_prompt
    assert "Coder summary only once" in qa_prompt
    assert "----- BEGIN SENIOR STAFF STRATEGY ANSWER -----" in reviewer_prompt
    assert "Full senior staff markdown artifact" in reviewer_prompt
    assert "----- BEGIN ARCHITECT PLAN ANSWER -----" in reviewer_prompt
    assert "Full architect markdown artifact" in reviewer_prompt
    assert "Full coder markdown artifact" not in reviewer_prompt
    assert "Coder summary only once" in reviewer_prompt
    assert "----- BEGIN QA VALIDATION REPORT ANSWER -----" in reviewer_prompt
    assert "Full QA validation markdown artifact" in reviewer_prompt
    assert '"answer"' not in reviewer_prompt
    assert '"summary_action"' not in reviewer_prompt
    assert "Previous role summaries" not in reviewer_prompt
    assert reviewer_prompt.count("Coder summary only once") == 1
    assert reviewer_prompt.count("QA summary only once") == 1
    assert reviewer_prompt.count("Senior staff summary only once") == 1

    publisher_prompt = build_publisher_prompt({**state, "reviewer_result": {"summary": {"summary": "Reviewer summary only once", "action": "PASS"}}})
    assert "----- BEGIN SENIOR STAFF STRATEGY ANSWER -----" in publisher_prompt
    assert "----- BEGIN ARCHITECT PLAN ANSWER -----" in publisher_prompt
    assert "Full architect markdown artifact" in publisher_prompt
    assert "Full coder markdown artifact" not in publisher_prompt
    assert publisher_prompt.count("QA summary only once") == 1
    assert publisher_prompt.count("Reviewer summary only once") == 1
    assert "gh" in publisher_prompt
    assert "GITHUB_TOKEN" in publisher_prompt


async def test_development_graph_happy_path_pass() -> None:
    pytest.importorskip("langgraph")
    runner = FakeDevelopmentRunner(["PASS"])
    graph = build_development_graph()

    result = await graph.ainvoke(
        {
            "user_task": "implement feature",
            "repository": "metacoma/repo",
            "git_provider": "github",
            "current_iteration": 0,
            "max_fix_iterations": 2,
        },
        config={"configurable": {"openhands_runner": runner}},
    )

    assert result["final_status"] == "completed"
    assert [call["role"] for call in runner.calls] == ["scout", "research", "senior_staff_engineer", "architect", "coder", "qa", "reviewer", "publisher"]
    assert len(result["role_results"]) == 8
    assert result["senior_staff_engineer_result"]["summary_action"] == "PROCEED"
    assert result["qa_result"]["summary_action"] == "PASS"
    assert result["reviewer_result"]["summary_action"] == "PASS"
    assert result["publisher_result"]["summary_action"] == "PASS"
    assert "scout answer 1" in runner.calls[1]["prompt"]
    assert "research answer 2" in runner.calls[2]["prompt"]
    assert "senior_staff_engineer answer 3" in runner.calls[3]["prompt"]
    assert "architect answer 4" in runner.calls[4]["prompt"]
    assert "architect answer 4" in runner.calls[5]["prompt"]
    assert "coder answer 5" not in runner.calls[5]["prompt"]
    assert "coder summary" in runner.calls[5]["prompt"]
    assert "architect answer 4" in runner.calls[6]["prompt"]
    assert "qa answer 6" in runner.calls[6]["prompt"]
    assert "CODER HANDOFF" not in runner.calls[6]["prompt"]
    assert "GITHUB_TOKEN" in runner.calls[7]["prompt"]
    assert "gh" in runner.calls[7]["prompt"]


async def test_development_graph_senior_staff_blocker_stops_before_architect() -> None:
    pytest.importorskip("langgraph")
    runner = FakeDevelopmentRunner(["PASS"], senior_staff_action="BLOCKER")
    graph = build_development_graph()

    result = await graph.ainvoke(
        {"user_task": "unsafe feature", "repository": "metacoma/repo", "current_iteration": 0, "max_fix_iterations": 2},
        config={"configurable": {"openhands_runner": runner}},
    )

    assert result["final_status"] == "blocked"
    assert [call["role"] for call in runner.calls] == ["scout", "research", "senior_staff_engineer"]
    assert "architect_result" not in result or result.get("architect_result") is None


async def test_development_graph_senior_staff_needs_research_stops_for_human_review() -> None:
    pytest.importorskip("langgraph")
    runner = FakeDevelopmentRunner(["PASS"], senior_staff_action="NEED_MORE_RESEARCH")
    graph = build_development_graph()

    result = await graph.ainvoke(
        {"user_task": "ambiguous runtime feature", "repository": "metacoma/repo", "current_iteration": 0, "max_fix_iterations": 2},
        config={"configurable": {"openhands_runner": runner}},
    )

    assert result["final_status"] == "needs_human_review"
    assert [call["role"] for call in runner.calls] == ["scout", "research", "senior_staff_engineer"]


async def test_development_graph_need_fix_retries_coder_then_passes() -> None:
    pytest.importorskip("langgraph")
    runner = FakeDevelopmentRunner(["NEED_FIX", "PASS"])
    graph = build_development_graph()

    result = await graph.ainvoke(
        {"user_task": "implement feature", "repository": "metacoma/repo", "current_iteration": 0, "max_fix_iterations": 2},
        config={"configurable": {"openhands_runner": runner}},
    )

    assert result["final_status"] == "completed"
    assert [call["role"] for call in runner.calls] == [
        "scout",
        "research",
        "senior_staff_engineer",
        "architect",
        "coder",
        "qa",
        "reviewer",
        "coder",
        "qa",
        "reviewer",
        "publisher",
    ]
    assert result["current_iteration"] == 1
    assert result["qa_result"]["summary_action"] == "PASS"
    assert result["reviewer_result"]["summary_action"] == "PASS"


async def test_development_graph_blocker_stops_pipeline() -> None:
    pytest.importorskip("langgraph")
    runner = FakeDevelopmentRunner(["BLOCKER"])
    graph = build_development_graph()

    result = await graph.ainvoke(
        {"user_task": "implement dangerous feature", "repository": "metacoma/repo", "current_iteration": 0, "max_fix_iterations": 2},
        config={"configurable": {"openhands_runner": runner}},
    )

    assert result["final_status"] == "blocked"
    assert [call["role"] for call in runner.calls] == ["scout", "research", "senior_staff_engineer", "architect", "coder", "qa", "reviewer"]
    assert result["reviewer_result"]["blocking"] is True


async def test_development_graph_max_fix_iterations_yields_human_review() -> None:
    pytest.importorskip("langgraph")
    runner = FakeDevelopmentRunner(["NEED_FIX", "NEED_FIX", "NEED_FIX"])
    graph = build_development_graph()

    result = await graph.ainvoke(
        {"user_task": "implement feature", "repository": "metacoma/repo", "current_iteration": 0, "max_fix_iterations": 1},
        config={"configurable": {"openhands_runner": runner}},
    )

    assert result["final_status"] == "needs_human_review"
    assert [call["role"] for call in runner.calls] == [
        "scout",
        "research",
        "senior_staff_engineer",
        "architect",
        "coder",
        "qa",
        "reviewer",
        "coder",
        "qa",
        "reviewer",
    ]
    assert result["current_iteration"] == 1


def test_development_graph_sets_per_role_titles() -> None:
    pytest.importorskip("langgraph")
    runner = FakeDevelopmentRunner(["PASS"])
    graph = build_development_graph()

    import asyncio

    result = asyncio.run(
        graph.ainvoke(
            {"user_task": "validate ruby grpc integration tests", "model": "openai/coder", "current_iteration": 0, "max_fix_iterations": 1},
            config={"configurable": {"openhands_runner": runner}},
        )
    )

    assert result["final_status"] == "completed"
    titles = [call.get("title") for call in runner.calls]
    assert titles == [
        "scout: validate ruby grpc integration tests",
        "research: validate ruby grpc integration tests",
        "senior_staff_engineer: validate ruby grpc integration tests",
        "architect: validate ruby grpc integration tests",
        "coder: validate ruby grpc integration tests",
        "qa: validate ruby grpc integration tests",
        "reviewer: validate ruby grpc integration tests",
        "publisher: validate ruby grpc integration tests",
    ]


def test_graph_cli_summary_attempts_default_is_three() -> None:
    from openhands_langgraph.cli import build_parser

    args = build_parser().parse_args(["--endpoint", "http://localhost:3000", "--prompt", "task"])

    assert args.summary_max_attempts == 3


def test_coder_qa_reviewer_have_mandatory_validation_tooling_rules() -> None:
    state = {
        "user_task": "fix CI failure",
        "senior_staff_engineer_result": {"role": "senior_staff_engineer", "summary": {"summary": "strategy"}, "answer": "strategy"},
        "architect_result": {"role": "architect", "summary": {"summary": "plan"}, "answer": "plan"},
        "coder_result": {"role": "coder", "summary": {"summary": "coder summary"}, "answer": "coder report"},
        "qa_result": {"role": "qa", "summary": {"summary": "qa summary", "action": "PASS", "validation": {"build_ran": True, "build_passed": True, "tests_run": True, "tests_passed": True, "validation_level": "targeted_runtime", "setup_commands": ["prepare documented validation layout"], "build_commands": ["./gradlew compileJava"], "test_commands": ["pytest smoke.py"], "validation_gaps": []}}, "answer": "qa report"},
    }
    coder_prompt = build_coder_prompt(state)
    qa_prompt = build_qa_prompt(state)
    reviewer_prompt = build_reviewer_prompt(state)

    assert "Compile/build" in coder_prompt or "compile/build" in coder_prompt
    assert "Install all necessary" in coder_prompt
    assert "Do not skip compilation/tests just because a tool is missing" in qa_prompt
    assert "install all necessary" in qa_prompt.lower()
    assert "install required linters/static checkers" in reviewer_prompt.lower()
    assert "changed file types" in reviewer_prompt
    for prompt in [coder_prompt, qa_prompt, reviewer_prompt]:
        assert "Debian Trixie" in prompt
        assert "sudo apt-get update" in prompt


def test_scout_prompt_is_facts_only_and_forbids_hypothesis_generation() -> None:
    prompt = build_scout_prompt({"user_task": "analyze failed GitHub Actions job"})
    lowered = prompt.lower()
    assert "factual context report" in lowered
    assert "strict facts-only rule" in lowered
    assert "do not produce root-cause hypotheses" in lowered
    assert "do not rank candidate causes" in lowered
    assert "validation questions for later roles" in lowered
    assert "# Scout Context Report" in prompt
    assert "Candidate Root Causes" not in prompt


def test_team_lead_prompt_tells_scout_to_collect_context_not_hypotheses() -> None:
    prompt = build_team_lead_prompt({"user_task": "inspect failed CI job", "team_lead_steps": 0, "max_team_lead_steps": 12})
    lowered = prompt.lower()
    assert "facts only" in lowered
    assert "when choosing scout" in lowered
    assert "do not ask scout for root-cause hypotheses" in lowered
