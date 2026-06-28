from __future__ import annotations

from openhands_langgraph.nodes import _validate_team_lead_decision
from openhands_langgraph.team_lead import TeamLeadDecision, _normalize_team_lead_decision_payload


def _pass_result(role: str, report_id: str, role_report: dict | None = None) -> dict:
    return {
        "role": role,
        "role_instance": f"{role}-1",
        "report_id": report_id,
        "ok": True,
        "summary_action": "PASS",
        "summary": {"action": "PASS", "summary": f"{role} pass"},
        "role_report": role_report or {"role": role, "report_id": report_id, "action": "PASS"},
        "answer": "done",
    }


def _external_publication_decision(action: str, next_role: str | None = None) -> TeamLeadDecision:
    decision = TeamLeadDecision(
        valid=True,
        status="completed",
        summary="external publication routing",
        action=action,
        risk_level="low",
        blocking=False,
        blocking_summary=[],
        next_role=next_role,
        role_instance=f"{next_role}-1" if next_role else None,
        context_sources=[],
        instructions="",
        reason="GitHub Discussion comment is a bounded external publication and does not require repository changes.",
    )
    decision.work_order = {
        "intent": "publish_comment",
        "target_system": "github_discussion",
        "change_surface": "external_publication",
        "artifact_kind": "published_comment",
        "execution_strategy": "direct_external_api",
        "risk_level": "low",
        "required_evidence": ["target_verified", "content_prepared", "publication_id"],
        "completed_evidence": [],
    }
    return decision


def test_external_publication_allows_publisher_without_coder_qa_or_reviewer() -> None:
    scout = _pass_result(
        "scout",
        "scout-report-1",
        {
            "role": "scout",
            "report_id": "scout-report-1",
            "action": "PASS",
            "summary": "Discussion target and release context collected; no repository changes required.",
            "facts": {"target": "GitHub Discussion #970", "repo_changes_required": False},
        },
    )
    state = {"role_results": [scout]}
    decision = _external_publication_decision("RUN_ROLE", "publisher")
    decision.accepted_report_ids = {"scout": "scout-report-1"}
    decision.policy_evaluation = {
        "can_publish": True,
        "publication_target_verified": True,
        "publication_content_reviewed": True,
        "no_repo_changes_accepted": True,
    }

    ok, reason = _validate_team_lead_decision(state, decision)

    assert ok is True, reason


def test_external_publication_rejects_coder_when_no_repo_changes_are_required() -> None:
    scout = _pass_result("scout", "scout-report-1")
    state = {"role_results": [scout]}
    decision = _external_publication_decision("RUN_ROLE", "coder")
    decision.accepted_report_ids = {"scout": "scout-report-1"}
    decision.policy_evaluation = {"can_publish": False}

    ok, reason = _validate_team_lead_decision(state, decision)

    assert ok is False
    assert reason is not None
    assert "external publication" in reason.lower()


def test_external_publication_stop_completed_accepts_publication_evidence_without_pr_checks() -> None:
    publisher = _pass_result(
        "publisher",
        "publisher-report-1",
        {
            "role": "publisher",
            "report_id": "publisher-report-1",
            "action": "PASS",
            "summary": "Comment posted to GitHub Discussion.",
            "publication": {
                "published": True,
                "target_type": "github_discussion_comment",
                "target_url": "https://github.com/metacoma/freeplane_plugin_grpc/discussions/970",
                "artifact_url": "https://github.com/metacoma/freeplane_plugin_grpc/discussions/970#discussioncomment-1",
                "comment_id": "DC_kwDOAFhh_M4BCn",
                "api": "github_graphql",
                "operation": "addDiscussionComment",
            },
        },
    )
    state = {"role_results": [publisher]}
    decision = _external_publication_decision("STOP_COMPLETED")
    decision.accepted_report_ids = {"publisher": "publisher-report-1"}
    decision.policy_evaluation = {
        "can_complete": True,
        "publisher_publication_evidence_accepted": True,
    }

    ok, reason = _validate_team_lead_decision(state, decision)

    assert ok is True, reason


def test_repository_stop_completed_still_requires_pr_checks_evidence() -> None:
    publisher = _pass_result(
        "publisher",
        "publisher-report-1",
        {
            "role": "publisher",
            "report_id": "publisher-report-1",
            "action": "PASS",
            "summary": "Only publication evidence, no PR checks.",
            "publication": {"published": True, "comment_id": "DC_1"},
        },
    )
    state = {"role_results": [publisher]}
    decision = TeamLeadDecision(
        valid=True,
        status="completed",
        summary="stop repository flow",
        action="STOP_COMPLETED",
        risk_level="low",
        blocking=False,
        blocking_summary=[],
        context_sources=[],
        instructions="",
        reason="",
    )
    decision.work_order = {
        "intent": "fix_code",
        "target_system": "repository",
        "change_surface": "repository",
        "artifact_kind": "pull_request",
        "execution_strategy": "repo_change",
    }
    decision.accepted_report_ids = {"publisher": "publisher-report-1"}
    decision.policy_evaluation = {"can_complete": True, "publisher_pr_checks_accepted": True}

    ok, reason = _validate_team_lead_decision(state, decision)

    assert ok is False
    assert reason is not None
    assert "head_sha" in reason or "pr" in reason.lower()


def test_team_lead_work_order_accepts_comma_separated_required_evidence() -> None:
    decision = TeamLeadDecision.model_validate(
        {
            "valid": True,
            "status": "completed",
            "summary": "route issue creation",
            "action": "RUN_ROLE",
            "risk_level": "low",
            "blocking": False,
            "next_role": "publisher",
            "role_instance": "publisher-1",
            "work_order": {
                "intent": "create_issue",
                "target_system": "github_issue",
                "change_surface": "external_publication",
                "artifact_kind": "issue",
                "execution_strategy": "direct_external_api",
                "required_evidence": "repo_exists_or_created, issue_created",
                "completed_evidence": "repo_exists_or_created",
            },
            "capabilities_required": "publish_comment, update_github_discussion",
            "blocking_summary": "",
            "context_sources": "scout-report-1, research-report-1",
            "future_workflow_plan": "publisher creates issue; stop when issue URL is returned",
            "instructions": "Create the GitHub issue directly.",
            "reason": "No repository mutation is needed.",
        }
    )

    assert decision.work_order.required_evidence == ["repo_exists_or_created", "issue_created"]
    assert decision.work_order.completed_evidence == ["repo_exists_or_created"]
    assert decision.capabilities_required == ["publish_comment", "update_github_discussion"]
    assert decision.context_sources == ["scout-report-1", "research-report-1"]
    assert decision.future_workflow_plan == ["publisher creates issue", "stop when issue URL is returned"]


def test_team_lead_pre_normalizer_converts_nested_string_lists_before_validation() -> None:
    payload = {
        "summary": "route issue creation",
        "action": "RUN_ROLE",
        "next_role": "publisher",
        "work_order": {
            "change_surface": "external_publication",
            "execution_strategy": "direct_external_api",
            "required_evidence": "repo_exists_or_created, issue_created",
            "completed_evidence": "repo_exists_or_created",
        },
        "capabilities_required": "create_issue, publish_comment",
        "policy_evaluation": {
            "blocking_reasons": "",
            "accepted_risks": "low-risk external publication",
        },
    }

    normalized = _normalize_team_lead_decision_payload(payload)
    decision = TeamLeadDecision.model_validate(normalized)

    assert normalized["work_order"]["required_evidence"] == ["repo_exists_or_created", "issue_created"]
    assert decision.work_order.required_evidence == ["repo_exists_or_created", "issue_created"]
    assert decision.capabilities_required == ["create_issue", "publish_comment"]
    assert decision.policy_evaluation.accepted_risks == ["low-risk external publication"]


def _repository_decision(action: str, next_role: str | None = None) -> TeamLeadDecision:
    decision = TeamLeadDecision(
        valid=True,
        status="completed",
        summary="repository routing",
        action=action,
        risk_level="medium",
        blocking=False,
        blocking_summary=[],
        next_role=next_role,
        role_instance=f"{next_role}-1" if next_role else None,
        context_sources=[],
        instructions="Publish the repository change." if next_role == "publisher" else "",
        reason="Repository change requires strict delivery gates.",
    )
    decision.work_order = {
        "intent": "fix_code",
        "target_system": "repository",
        "change_surface": "repository",
        "artifact_kind": "pull_request",
        "execution_strategy": "repo_change",
        "required_evidence": ["implementation", "documentation_updated_or_waived", "pr_checks"],
    }
    return decision


def test_repository_publisher_rejects_missing_documentation_evidence() -> None:
    coder = _pass_result("coder", "coder-report-1")
    qa = _pass_result("qa", "qa-report-1")
    reviewer = _pass_result("reviewer", "reviewer-report-1")
    state = {"role_results": [coder, qa, reviewer]}
    decision = _repository_decision("RUN_ROLE", "publisher")
    decision.policy_evaluation = {
        "can_publish": True,
        "documentation_impact_assessed": True,
        "documentation_updated_or_waived": True,
    }

    ok, reason = _validate_team_lead_decision(state, decision)

    assert ok is False
    assert reason is not None
    assert "documentation" in reason.lower()


def test_repository_publisher_accepts_reviewer_documentation_waiver() -> None:
    coder = _pass_result(
        "coder",
        "coder-report-1",
        {
            "role": "coder",
            "report_id": "coder-report-1",
            "action": "PASS",
            "documentation": {
                "impact_assessed": True,
                "required": False,
                "updated": False,
                "files": [],
                "reason": "Internal helper refactor only.",
                "waiver_reason": "No user-facing behavior, config, CLI, API, deployment, workflow, examples, or installation docs changed.",
            },
        },
    )
    qa = _pass_result("qa", "qa-report-1")
    reviewer = _pass_result(
        "reviewer",
        "reviewer-report-1",
        {
            "role": "reviewer",
            "report_id": "reviewer-report-1",
            "action": "PASS",
            "documentation": {
                "impact_assessed": True,
                "required": False,
                "updated": False,
                "files": [],
                "reason": "Reviewer inspected the diff and confirmed the change is internal-only.",
                "waiver_reason": "No public behavior, config, CLI, API, deployment workflow, examples, or installation docs changed.",
            },
        },
    )
    state = {"role_results": [coder, qa, reviewer]}
    decision = _repository_decision("RUN_ROLE", "publisher")
    decision.policy_evaluation = {
        "can_publish": True,
        "documentation_impact_assessed": True,
        "documentation_updated_or_waived": True,
    }

    ok, reason = _validate_team_lead_decision(state, decision)

    assert ok is True, reason


def test_repository_publisher_accepts_required_docs_updated() -> None:
    documentation = {
        "impact_assessed": True,
        "required": True,
        "updated": True,
        "files": ["README.md", "docs/work-order.md"],
        "reason": "New CLI/work-order behavior is user-visible and documented.",
        "waiver_reason": None,
    }
    coder = _pass_result("coder", "coder-report-1", {"role": "coder", "report_id": "coder-report-1", "action": "PASS", "documentation": documentation})
    qa = _pass_result("qa", "qa-report-1", {"role": "qa", "report_id": "qa-report-1", "action": "PASS", "documentation": documentation})
    reviewer = _pass_result("reviewer", "reviewer-report-1", {"role": "reviewer", "report_id": "reviewer-report-1", "action": "PASS", "documentation": documentation})
    state = {"role_results": [coder, qa, reviewer]}
    decision = _repository_decision("RUN_ROLE", "publisher")
    decision.policy_evaluation = {
        "can_publish": True,
        "documentation_impact_assessed": True,
        "documentation_updated_or_waived": True,
        "documentation_required": True,
        "documentation_updated": True,
    }

    ok, reason = _validate_team_lead_decision(state, decision)

    assert ok is True, reason


def test_work_order_accepts_comma_separated_documentation_targets() -> None:
    decision = TeamLeadDecision.model_validate(
        {
            "valid": True,
            "status": "completed",
            "summary": "route repo change",
            "action": "RUN_ROLE",
            "next_role": "coder",
            "work_order": {
                "change_surface": "repository",
                "execution_strategy": "repo_change",
                "documentation_required": True,
                "documentation_targets": "README.md, docs/config.md",
            },
            "instructions": "Implement and update docs.",
            "reason": "Repository change.",
        }
    )

    assert decision.work_order.documentation_targets == ["README.md", "docs/config.md"]
