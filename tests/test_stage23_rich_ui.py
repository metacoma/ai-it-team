from __future__ import annotations

from collections import deque

from openhands_langgraph.cli import build_parser
from openhands_langgraph.ui import NullWorkflowUI, RoleUIState, make_workflow_ui


def test_ui_cli_flags_exist() -> None:
    args = build_parser().parse_args([
        "--endpoint", "http://localhost:3000",
        "--prompt", "x",
        "--ui", "plain",
        "--ui-prompt-chars", "1234",
        "--ui-answer-chars", "5678",
    ])
    assert args.ui == "plain"
    assert args.ui_prompt_chars == 1234
    assert args.ui_answer_chars == 5678


def test_plain_ui_is_noop() -> None:
    ui = make_workflow_ui("plain")
    assert isinstance(ui, NullWorkflowUI)
    ui.start()
    ui.role_start("qa", "prompt")
    ui.role_event_callback("qa")({"kind": "MessageEvent", "source": "agent", "message": "hello"})
    ui.role_result("qa", {"summary": {"action": "PASS", "summary": "ok"}})
    ui.final_result({"final_status": "completed"})
    ui.stop()


def test_role_ui_state_keeps_last_five_events() -> None:
    state = RoleUIState(role="qa")
    for idx in range(8):
        state.last_events.append(f"event-{idx}")
    assert isinstance(state.last_events, deque)
    assert list(state.last_events) == ["event-3", "event-4", "event-5", "event-6", "event-7"]

from openhands_langgraph.ui import EventLine, build_prompt_digest, classify_event_line


def test_prompt_digest_prefers_substitutions_over_full_prompt() -> None:
    state = {
        "workflow": "team-lead",
        "user_task": "Fix CI failure in Node.js gRPC integration tests",
        "repository": "metacoma/freeplane_plugin_grpc",
        "team_lead_steps": 2,
        "max_team_lead_steps": 12,
        "team_lead_decision": {
            "action": "RUN_ROLE",
            "next_role": "qa",
            "instructions": "Validate required integration targets end-to-end.",
        },
        "validation_profile": {
            "required_targets": [
                {"name": "nodejs_integration", "required": True, "required_by": "ci"}
            ]
        },
    }
    prompt = "STATIC POLICY\n" * 1000
    digest = build_prompt_digest("qa", prompt, state=state, max_chars=2000)
    joined = "\n".join(digest)
    assert "Fix CI failure" in joined
    assert "nodejs_integration" in joined
    assert "STATIC POLICY" not in joined


def test_event_classification_adds_styles() -> None:
    event = {"kind": "ActionEvent", "tool_name": "bash", "action": {"command": "pytest"}}
    line = classify_event_line(event, "[action:bash] pytest")
    assert isinstance(line, EventLine)
    assert line.kind == "action"
    assert "yellow" in line.style


def test_rich_ui_event_callback_keeps_colored_last_five_lines() -> None:
    ui = make_workflow_ui("rich", no_color=True)
    ui.role_start("coder", "long full prompt that should not be shown", state={"user_task": "task"})
    callback = ui.role_event_callback("coder")
    for idx in range(7):
        callback({"kind": "ActionEvent", "tool_name": "bash", "action": {"command": f"cmd-{idx}"}})
    assert ui.current is not None
    assert len(ui.current.last_events) == 5
    assert all(isinstance(item, EventLine) for item in ui.current.last_events)
    assert str(ui.current.last_events[-1]) == "[bash] $ cmd-6"
