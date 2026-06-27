from __future__ import annotations

from typing import Any

import pytest

from openhands import OpenHandsRoleRunner
from openhands.models import AppConversationStart, OpenHandsRunResult, RoleRunResult, RoleSummary
from openhands_langgraph.nodes import dynamic_role_executor_node, team_lead_node
from openhands_langgraph.prompts import build_team_lead_prompt


class FailingRunner(OpenHandsRoleRunner):
    def __init__(self, error: str = "Failed to parse tool call arguments as JSON: unexpected end of input") -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def run_role(self, **kwargs: Any) -> RoleRunResult:  # type: ignore[override]
        self.calls.append(kwargs)
        raise RuntimeError(self.error)


class TeamLeadDecisionRunner:
    def __init__(self, *, next_role: str, action: str = "RUN_ROLE", instructions: str = "test instructions") -> None:
        from openhands_langgraph.team_lead import TeamLeadDecision, TeamLeadDecisionResult

        self.next_role = next_role
        self.action = action
        self.instructions = instructions
        self.calls: list[dict[str, Any]] = []
        self.TeamLeadDecision = TeamLeadDecision
        self.TeamLeadDecisionResult = TeamLeadDecisionResult

    async def decide(self, **kwargs: Any):
        self.calls.append(kwargs)
        decision = self.TeamLeadDecision(
            valid=True,
            status="completed",
            summary=f"Team Lead requests {self.next_role}",
            action=self.action,
            risk_level="low",
            blocking=False,
            blocking_summary=[],
            next_role=self.next_role if self.action in {"RUN_ROLE", "RETRY_ROLE"} else None,
            role_instance=f"{self.next_role}-1" if self.action in {"RUN_ROLE", "RETRY_ROLE"} else None,
            context_sources=["test"],
            instructions=self.instructions,
            reason="test reason",
        )
        return self.TeamLeadDecisionResult(decision=decision, raw_response=decision.model_dump_json(), attempts=1, model="fake")


def _failed_coder_result() -> dict[str, Any]:
    return {
        "role": "coder",
        "role_instance": "coder-1",
        "conversation_id": "coder-conv",
        "status": "failed",
        "ok": False,
        "summary_status": "failed",
        "summary_action": "FAILED",
        "risk_level": "high",
        "blocking": True,
        "error_type": "llm_tool_call_json_parse_error",
        "retryable": True,
        "error": "Failed to parse tool call arguments as JSON: unexpected end of input",
        "summary": {
            "valid": True,
            "status": "failed",
            "summary": "coder runtime failure",
            "action": "FAILED",
            "risk_level": "high",
            "blocking": True,
            "blocking_summary": ["Failed to parse tool call arguments as JSON"],
        },
        "answer": "",
        "metrics": {"duration_seconds": 1.0, "summary_attempt_count": 0},
    }


@pytest.mark.asyncio
async def test_dynamic_role_executor_records_failed_role_result() -> None:
    runner = FailingRunner()

    result = await dynamic_role_executor_node(
        {
            "user_task": "fix bug",
            "pending_role": "coder",
            "pending_role_instance": "coder-1",
            "architect_result": {
                "role": "architect",
                "ok": True,
                "summary_action": "PASS",
                "summary": {"summary": "plan", "action": "PASS"},
                "answer": "architect plan",
            },
            "role_results": [],
            "role_sessions": {},
        },
        config={"configurable": {"openhands_runner": runner}},
    )

    assert result["final_status"] == "failed"
    assert result["errors"]
    assert len(result["role_results"]) == 1
    failed = result["role_results"][0]
    assert failed["role"] == "coder"
    assert failed["role_instance"] == "coder-1"
    assert failed["ok"] is False
    assert failed["summary_action"] == "FAILED"
    assert failed["error_type"] == "llm_tool_call_json_parse_error"
    assert failed["retryable"] is True
    assert result["coder_result"]["ok"] is False


@pytest.mark.asyncio
async def test_team_lead_cannot_run_reviewer_after_failed_coder() -> None:
    runner = TeamLeadDecisionRunner(next_role="reviewer")
    failed = _failed_coder_result()

    result = await team_lead_node(
        {
            "user_task": "fix bug",
            "team_lead_steps": 1,
            "max_team_lead_steps": 12,
            "architect_result": {
                "role": "architect",
                "ok": True,
                "summary_action": "PASS",
                "summary": {"summary": "plan", "action": "PASS"},
                "answer": "architect plan",
            },
            "coder_result": failed,
            "role_results": [failed],
            "role_sessions": {},
            "errors": ["coder failed"],
        },
        config={"configurable": {"team_lead_runner": runner}},
    )

    assert result["final_status"] == "needs_human_review"
    assert "Last specialist role coder failed" in result["final_answer"]
    assert any("Last specialist role coder failed" in err for err in result["errors"])


@pytest.mark.asyncio
async def test_team_lead_can_retry_same_failed_role() -> None:
    runner = TeamLeadDecisionRunner(next_role="coder", action="RETRY_ROLE")
    failed = _failed_coder_result()

    result = await team_lead_node(
        {
            "user_task": "fix bug",
            "team_lead_steps": 1,
            "max_team_lead_steps": 12,
            "architect_result": {
                "role": "architect",
                "ok": True,
                "summary_action": "PASS",
                "summary": {"summary": "plan", "action": "PASS"},
                "answer": "architect plan",
            },
            "coder_result": failed,
            "role_results": [failed],
            "role_sessions": {},
            "errors": ["coder failed"],
        },
        config={"configurable": {"team_lead_runner": runner}},
    )

    assert result["final_status"] == "team_lead_selected_role"
    assert result["next_node"] == "role_executor"
    assert result["pending_role"] == "coder"
    assert result["pending_role_instance"] == "coder-1"


def test_team_lead_prompt_separates_decisions_successes_and_failures() -> None:
    failed = _failed_coder_result()
    prompt = build_team_lead_prompt(
        {
            "user_task": "fix bug",
            "team_lead_steps": 3,
            "max_team_lead_steps": 12,
            "role_results": [
                {
                    "role": "team_lead",
                    "role_instance": "team_lead-1",
                    "ok": True,
                    "summary_action": "RUN_ROLE",
                    "summary": {
                        "summary": "Run coder",
                        "action": "RUN_ROLE",
                        "next_role": "coder",
                        "role_instance": "coder-1",
                    },
                },
                failed,
            ],
        }
    )

    assert "Workflow history:" in prompt
    assert "Specialist role results:" in prompt
    assert "Failed specialist role attempts:" in prompt
    assert "Previous Team Lead decisions:" in prompt
    assert "Requested roles without specialist result:" in prompt
    assert "coder-1 (coder) status=failed" in prompt
    assert "Do not assume it completed" not in prompt  # failed result is present, not absent
    assert "A Team Lead RUN_ROLE decision only means a role was requested" in prompt
    assert "Never assume a role completed" in prompt


@pytest.mark.asyncio
async def test_team_lead_scout_instructions_are_sanitized_to_facts_only() -> None:
    runner = TeamLeadDecisionRunner(
        next_role="scout",
        instructions=(
            "Analyze CI failure and report the root cause hypothesis, likely cause, "
            "candidate root causes, and stack trace."
        ),
    )

    result = await team_lead_node(
        {
            "user_task": "inspect failed CI job",
            "team_lead_steps": 0,
            "max_team_lead_steps": 12,
            "role_results": [],
            "role_sessions": {},
        },
        config={"configurable": {"team_lead_runner": runner}},
    )

    assert result["final_status"] == "team_lead_selected_role"
    decision = result["team_lead_decision"]
    assert decision["next_role"] == "scout"
    instructions = decision["instructions"].lower()
    assert "factual context only" in instructions
    assert "validation questions" in instructions
    assert "do not propose causal explanations" in instructions
    assert "root cause hypothesis" not in instructions
    assert "candidate root causes" not in instructions
    assert "likely cause" not in instructions
