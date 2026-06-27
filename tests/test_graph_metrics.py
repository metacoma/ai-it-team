from __future__ import annotations

from openhands_langgraph.cli import _duration_text, _print_human_result


def test_duration_text_formats_human_readable_values() -> None:
    assert _duration_text(0.25) == "250ms"
    assert _duration_text(2.345).endswith("s")
    assert _duration_text(65) == "1m 5s"


def test_human_result_prints_metrics_section(capsys) -> None:
    _print_human_result(
        {
            "final_status": "completed",
            "workflow_metrics": {
                "duration_seconds": 65,
                "role_count": 2,
                "summary_attempt_count": 3,
                "current_iteration": 1,
                "max_fix_iterations": 2,
                "actions": {"PASS": 1, "CONTINUE": 1},
                "started_at": "2026-06-15T10:00:00Z",
                "finished_at": "2026-06-15T10:01:05Z",
            },
            "role_results": [
                {
                    "role": "scout",
                    "ok": True,
                    "summary_action": "CONTINUE",
                    "risk_level": "low",
                    "blocking": False,
                    "conversation_id": "conv-1",
                    "metrics": {"duration_seconds": 10, "summary_attempt_count": 1, "answer_chars": 42},
                    "summary": {"summary": "scout summary"},
                },
                {
                    "role": "reviewer",
                    "ok": True,
                    "summary_action": "PASS",
                    "risk_level": "low",
                    "blocking": False,
                    "conversation_id": "conv-2",
                    "metrics": {"duration_seconds": 55, "summary_attempt_count": 2, "answer_chars": 100},
                    "summary": {"summary": "reviewer summary"},
                },
            ],
        },
        color=False,
    )

    out = capsys.readouterr().out
    assert "Metrics:" in out
    assert "total duration: 1m 5s" in out
    assert "roles executed: 2" in out
    assert "summary attempts: 3" in out
    assert "fix iterations: 1/2" in out
    assert "Per-role results:" in out
    assert "duration: 10.0s" in out
    assert "summary attempts: 2" in out
