from openhands_langgraph.nodes import (
    _drop_recovered_role_errors,
    _has_qa_pass,
    _has_reviewer_pass,
    _reviewer_pass_gate,
    _validate_team_lead_decision,
    qa_decision_node,
    review_decision_node,
)
from openhands_langgraph.prompts import build_qa_prompt, build_reviewer_prompt, build_role_summary_instructions, build_team_lead_decision_prompt


def test_qa_prompt_forbids_out_of_scope_runtime_tests() -> None:
    prompt = build_qa_prompt({"user_task": "fix failed CI integration test"})
    assert 'Never declare relevant CI/runtime/integration/smoke tests "beyond scope"' in prompt
    assert "QA PASS is forbidden" in prompt
    assert "Validation Evidence JSON" in prompt
    assert "Validation Environment Setup" in prompt
    assert "upstream source checkout" in prompt


def test_reviewer_prompt_rejects_qa_without_evidence() -> None:
    prompt = build_reviewer_prompt({"user_task": "fix failed CI integration test"})
    assert "QA returned PASS without build/test evidence" in prompt
    assert "If QA skipped relevant runtime/integration/smoke tests as out-of-scope" in prompt
    assert "syntax-level validation" in prompt
    assert "upstream/core project" in prompt


def test_qa_summary_instructions_require_validation_object() -> None:
    instructions = build_role_summary_instructions("qa")
    assert "extra key validation" in instructions
    assert "build_ran" in instructions
    assert "tests_run" in instructions
    assert "validation_level" in instructions
    assert "setup_commands" in instructions
    assert "PASS requires" in instructions


def test_has_qa_pass_requires_build_and_test_evidence() -> None:
    state = {
        "role_results": [
            {
                "role": "qa",
                "role_instance": "qa-1",
                "ok": True,
                "summary_action": "PASS",
                "summary": {"action": "PASS", "summary": "looks good"},
            }
        ]
    }
    assert _has_qa_pass(state) is False

    state["role_results"][0]["summary"]["validation"] = {
        "build_ran": True,
        "build_passed": True,
        "tests_run": True,
        "tests_passed": True,
        "validation_level": "targeted_runtime",
        "setup_commands": ["prepare documented validation layout"],
        "build_commands": ["./gradlew compileJava"],
        "test_commands": ["pytest smoke.py"],
        "validation_gaps": [],
    }
    assert _has_qa_pass(state) is True


def test_qa_decision_does_not_route_to_reviewer_without_evidence() -> None:
    state = {
        "qa_result": {
            "role": "qa",
            "ok": True,
            "summary_action": "PASS",
            "summary": {"action": "PASS", "summary": "No tests were run; beyond scope."},
        },
        "current_iteration": 0,
        "max_fix_iterations": 2,
    }
    result = qa_decision_node(state)
    assert result["next_node"] == "end"
    assert result["final_status"] == "needs_human_review"
    assert "without required build/test evidence" in result["final_answer"]


def test_team_lead_prompt_mentions_qa_evidence_gate() -> None:
    prompt = build_team_lead_decision_prompt({"user_task": "fix CI"})
    assert "QA PASS includes build/test validation evidence" in prompt
    assert "out of scope" in prompt


def test_qa_pass_rejects_syntax_only_or_missing_upstream_gap() -> None:
    state = {
        "role_results": [
            {
                "role": "qa",
                "role_instance": "qa-1",
                "ok": True,
                "summary_action": "PASS",
                "summary": {
                    "action": "PASS",
                    "summary": "Only syntax-level validation; Freeplane core project is not present",
                    "validation": {
                        "build_ran": True,
                        "build_passed": True,
                        "tests_run": True,
                        "tests_passed": True,
                        "validation_level": "syntax_only",
                        "build_commands": ["javac -Xlint Foo.java"],
                        "test_commands": ["ruby -c example.rb"],
                        "validation_gaps": ["core project is not present; full build not run"],
                    },
                },
                "answer": "qa report",
            }
        ]
    }
    assert _has_qa_pass(state) is False


def test_reviewer_pass_requires_validation_review_object() -> None:
    state = {
        "role_results": [
            {
                "role": "reviewer",
                "role_instance": "reviewer-1",
                "ok": True,
                "summary_action": "PASS",
                "summary": {"action": "PASS", "summary": "Looks good but no validation review."},
                "answer": "reviewer report",
            }
        ]
    }
    assert _has_reviewer_pass(state) is False

    state["role_results"][0]["summary"]["validation_review"] = {
        "qa_build_evidence_ok": True,
        "qa_test_evidence_ok": True,
        "qa_validation_level_ok": True,
        "environment_reconstruction_reviewed": True,
        "syntax_only_rejected": True,
        "lint_commands": ["python -m py_compile example.py"],
        "setup_commands_reviewed": ["prepare documented validation layout"],
        "validation_gaps": [],
    }
    assert _has_reviewer_pass(state) is True


def test_review_decision_does_not_route_to_publisher_without_validation_review() -> None:
    state = {
        "reviewer_result": {
            "role": "reviewer",
            "ok": True,
            "summary_action": "PASS",
            "summary": {"action": "PASS", "summary": "Diff looks good."},
            "answer": "reviewer report",
        },
        "current_iteration": 0,
        "max_fix_iterations": 2,
    }
    result = review_decision_node(state)
    assert result["next_node"] == "end"
    assert result["final_status"] == "needs_human_review"
    assert "validation review evidence" in result["final_answer"]


def test_qa_pass_can_use_validation_json_from_full_answer_when_summary_omits_it() -> None:
    state = {
        "role_results": [
            {
                "role": "qa",
                "role_instance": "qa-1",
                "ok": True,
                "summary_action": "PASS",
                "summary": {"action": "PASS", "summary": "Build and smoke tests passed."},
                "answer": '''# QA Report
## Validation Evidence JSON
{"validation": {"build_ran": true, "build_passed": true, "tests_run": true, "tests_passed": true, "validation_level": "ci_like", "install_commands": ["sudo apt-get install -y xvfb"], "setup_commands": ["git clone https://github.com/freeplane/freeplane /tmp/freeplane"], "build_commands": ["./gradlew build"], "test_commands": ["pytest tests/test_json_roundtrip.py"], "validation_gaps": []}}
''',
            }
        ]
    }
    assert _has_qa_pass(state) is True


def test_qa_decision_routes_to_reviewer_when_validation_json_is_only_in_answer() -> None:
    state = {
        "qa_result": {
            "role": "qa",
            "ok": True,
            "summary_action": "PASS",
            "summary": {"action": "PASS", "summary": "CI-like build and smoke tests passed."},
            "answer": '''{"validation": {"build_ran": true, "build_passed": true, "tests_run": true, "tests_passed": true, "validation_level": "targeted_runtime", "install_commands": [], "setup_commands": ["prepare layout"], "build_commands": ["./gradlew build"], "test_commands": ["pytest smoke.py"], "validation_gaps": []}}''',
        },
        "current_iteration": 0,
        "max_fix_iterations": 2,
    }
    result = qa_decision_node(state)
    assert result["next_node"] == "reviewer"
    assert result["final_status"] == "qa_passed"


def test_reviewer_pass_can_use_validation_review_json_from_full_answer() -> None:
    state = {
        "role_results": [
            {
                "role": "reviewer",
                "role_instance": "reviewer-1",
                "ok": True,
                "summary_action": "PASS",
                "summary": {"action": "PASS", "summary": "Review passed."},
                "answer": '''{"validation_review": {"qa_build_evidence_ok": true, "qa_test_evidence_ok": true, "qa_validation_level_ok": true, "environment_reconstruction_reviewed": true, "syntax_only_rejected": true, "lint_commands": ["javac -Xlint"], "setup_commands_reviewed": ["prepare layout"], "validation_gaps": []}}''',
            }
        ]
    }
    assert _has_reviewer_pass(state) is True


def _qa_pass_result(role_instance: str = "qa-2") -> dict:
    return {
        "role": "qa",
        "role_instance": role_instance,
        "ok": True,
        "summary_action": "PASS",
        "summary": {
            "action": "PASS",
            "summary": "deleteChild EDT dispatch fix compiles cleanly and all 12/12 tests pass.",
            "validation": {
                "build_ran": True,
                "build_passed": True,
                "tests_run": True,
                "tests_passed": True,
                "validation_level": "targeted_integration",
                "install_commands": [],
                "setup_commands": [
                    "cp FreeplaneGrpcService.java to /tmp/freeplane/freeplane_plugin_grpc/",
                    "gradle dist -x test -x check_translation --no-daemon",
                    "/tmp/freeplane/BIN/freeplane.sh smoke_test_map.mm",
                ],
                "build_commands": [
                    "gradle :freeplane_plugin_grpc:compileJava --no-daemon (Java 17)",
                    "gradle dist -x test -x check_translation --no-daemon (Java 17)",
                ],
                "test_commands": ["python3 grpc/python/examples/test_json_roundtrip.py"],
                "validation_gaps": [
                    "createChild, moveNode, setNodeText still lack EDT dispatch (latent bugs, deferred to follow-up)",
                ],
            },
        },
        "answer": "QA report with targeted integration validation evidence",
    }


def test_qa_pass_allows_non_blocking_validation_gaps_after_targeted_integration_passed() -> None:
    state = {"role_results": [_qa_pass_result()]}
    assert _has_qa_pass(state) is True




def test_qa_pass_blocks_skipped_ci_suite_due_missing_installable_tool() -> None:
    qa = _qa_pass_result()
    qa["summary"]["validation"]["validation_gaps"] = [
        "Ruby integration tests not run — Ruby and bundler are not installed in the sandbox. The CI runs Ruby tests before Python tests. These should be verified in the actual CI pipeline."
    ]
    state = {"role_results": [qa]}
    assert _has_qa_pass(state) is False


def test_qa_pass_blocks_actual_ci_pipeline_deferment_even_with_tests_passed() -> None:
    qa = _qa_pass_result()
    qa["summary"]["validation"]["validation_gaps"] = [
        "Some CI-listed runtime tests should be verified in the actual CI pipeline"
    ]
    state = {"role_results": [qa]}
    assert _has_qa_pass(state) is False


def test_qa_pass_uses_latest_qa_after_latest_coder_retry() -> None:
    older_qa_need_fix = {
        "role": "qa",
        "role_instance": "qa-1",
        "ok": True,
        "summary_action": "NEED_FIX",
        "summary": {"action": "NEED_FIX", "summary": "4/10 tests pass; deleteChild still failing."},
        "answer": "needs fix",
    }
    state = {
        # Deliberately stale snapshot: retry-aware guards must use append-only history.
        "qa_result": older_qa_need_fix,
        "role_results": [
            {
                "role": "coder",
                "role_instance": "coder-1",
                "ok": True,
                "summary_action": "PASS",
                "summary": {"action": "PASS", "summary": "first implementation"},
                "answer": "code changed",
            },
            older_qa_need_fix,
            {
                "role": "coder",
                "role_instance": "coder-1",
                "ok": True,
                "summary_action": "PASS",
                "summary": {"action": "PASS", "summary": "retry implementation"},
                "answer": "code changed again",
            },
            _qa_pass_result("qa-1"),
        ],
    }
    assert _has_qa_pass(state) is True


def test_qa_before_latest_coder_retry_does_not_unlock_reviewer() -> None:
    state = {
        "role_results": [
            {
                "role": "coder",
                "role_instance": "coder-1",
                "ok": True,
                "summary_action": "PASS",
                "summary": {"action": "PASS", "summary": "first implementation"},
                "answer": "code changed",
            },
            _qa_pass_result("qa-1"),
            {
                "role": "coder",
                "role_instance": "coder-1",
                "ok": True,
                "summary_action": "PASS",
                "summary": {"action": "PASS", "summary": "retry changed code after QA"},
                "answer": "code changed after qa",
            },
        ]
    }
    assert _has_qa_pass(state) is False



def _reviewer_prose_pass_result(role_instance: str = "reviewer-1") -> dict:
    return {
        "role": "reviewer",
        "role_instance": role_instance,
        "ok": True,
        "summary_action": "PASS",
        "summary": {
            "action": "PASS",
            "summary": "Two-part fix verified. QA full runtime validation completed in sandbox with Java build SUCCESS, Xvfb + Freeplane runtime, and integration/smoke tests passed. Diff review and syntax/static checks are acceptable.",
        },
        "answer": """
# Reviewer Report
PASS.
QA evidence reviewed: Java build/compile passed successfully and QA runtime validation used Xvfb + Freeplane runtime.
QA test evidence reviewed: smoke/integration tests passed in sandbox; this was runtime validation, not syntax-only validation.
I also reviewed changed files and performed relevant syntax/static checks for Java/YAML/shell changes.
""",
    }


def test_reviewer_pass_can_use_explicit_prose_evidence_when_json_missing() -> None:
    state = {"role_results": [_reviewer_prose_pass_result()]}
    assert _has_reviewer_pass(state) is True
    ok, reason = _reviewer_pass_gate(state)
    assert ok is True
    assert reason is None


def test_publisher_gate_uses_latest_qa_and_reviewer_after_recovered_qa_failure() -> None:
    failed_qa = {
        "role": "qa",
        "role_instance": "qa-1",
        "ok": False,
        "summary_action": "FAILED",
        "summary": {"action": "FAILED", "summary": "qa runtime failure"},
        "answer": "",
    }
    qa_pass = _qa_pass_result("qa-1")
    reviewer_pass = _reviewer_prose_pass_result("reviewer-1")
    state = {
        "errors": ["qa: main OpenHands run finished without an assistant answer; cannot summarize"],
        "role_results": [
            {
                "role": "coder",
                "role_instance": "coder-1",
                "ok": True,
                "summary_action": "PASS",
                "summary": {"action": "PASS", "summary": "implementation"},
                "answer": "code changed",
            },
            failed_qa,
            qa_pass,
            reviewer_pass,
        ],
    }
    ok, reason = _validate_team_lead_decision(
        state,
        {
            "action": "RUN_ROLE",
            "next_role": "publisher",
            "policy_evaluation": {"can_publish": True},
        },
    )
    assert ok is True
    assert reason is None


def test_publisher_gate_reports_reviewer_reason_separately() -> None:
    state = {
        "role_results": [
            {
                "role": "coder",
                "role_instance": "coder-1",
                "ok": True,
                "summary_action": "PASS",
                "summary": {"action": "PASS", "summary": "implementation"},
                "answer": "code changed",
            },
            _qa_pass_result("qa-1"),
            {
                "role": "reviewer",
                "role_instance": "reviewer-1",
                "ok": True,
                "summary_action": "PASS",
                "summary": {"action": "PASS", "summary": "Looks good."},
                "answer": "Looks good but no validation review.",
            },
        ],
    }
    ok, reason = _validate_team_lead_decision(state, {"action": "RUN_ROLE", "next_role": "publisher"})
    assert ok is False
    assert "policy_evaluation.can_publish" in reason

    ok, reason = _validate_team_lead_decision(
        state,
        {"action": "RUN_ROLE", "next_role": "publisher", "policy_evaluation": {"can_publish": True}},
    )
    assert ok is True
    assert reason is None


def test_recovered_role_error_is_removed_from_active_errors() -> None:
    errors = [
        "qa: main OpenHands run finished without an assistant answer; cannot summarize",
        "Team Lead requested publisher before accepted Reviewer PASS: missing validation_review",
    ]
    assert _drop_recovered_role_errors(errors, "qa") == [
        "Team Lead requested publisher before accepted Reviewer PASS: missing validation_review"
    ]


def test_qa_prompt_requires_repo_scripts_before_ci_only_claim() -> None:
    prompt = build_qa_prompt({"user_task": "fix Freeplane Xvfb gRPC CI failure"})
    assert "repository-provided helper scripts" in prompt
    assert "FREEPLANE_HOST" in prompt
    assert "Repository-provided scripts are authoritative validation entry points" in prompt
    assert "cannot be validated locally without starting Freeplane" in prompt


def test_qa_pass_blocks_full_ci_pipeline_xvfb_freeplane_excuse_in_full_answer() -> None:
    qa = _qa_pass_result()
    qa["summary"]["validation"]["validation_gaps"] = []
    qa["answer"] = """
# QA Report
## Validation Gaps
Runtime deadlock fix: Cannot be validated locally without starting Freeplane in Xvfb and connecting via gRPC. This requires the full CI pipeline (Xvfb, openbox, Freeplane binary, gRPC server startup). The fix is structurally correct.
Ruby integration tests: Excluded by default without FREEPLANE_HOST environment variable.
Python smoke tests require a live Freeplane gRPC server.
"""
    state = {"role_results": [qa]}
    assert _has_qa_pass(state) is False


def test_reviewer_pass_blocks_when_reviewer_accepts_ci_only_runtime_gap() -> None:
    reviewer = _reviewer_prose_pass_result()
    reviewer["answer"] += "\nQA gap accepted: cannot run in this sandbox; should be confirmed in the actual CI pipeline."
    state = {"role_results": [reviewer]}
    assert _has_reviewer_pass(state) is False


def test_team_lead_prompt_rejects_skipped_required_qa_targets() -> None:
    prompt = build_team_lead_decision_prompt({"user_task": "fix runtime CI smoke test"})

    assert "QA action=PASS is only QA's recommendation" in prompt
    assert "validation_level=targeted_unit is insufficient" in prompt
    assert "Skipped tests are not passing tests" in prompt
    assert "integration tests skipped gracefully" in prompt
