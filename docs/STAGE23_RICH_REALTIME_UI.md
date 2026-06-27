# Stage 23 — Rich real-time workflow UI

v53 adds an operator-oriented terminal UI based on `rich`.

Goals:

- show the current role prompt while the role is running;
- show the last five OpenHands websocket messages/events in real time;
- show the latest assistant answer preview while the role is running;
- show the completed role answer and compact summary after each role;
- preserve `--output-json` and the old plain trace modes.

## CLI

```bash
openhands-graph-run \
  --workflow team-lead \
  --endpoint http://localhost:3000 \
  --model openai/coder \
  --team-lead-base-url http://127.0.0.1:4000/v1 \
  --team-lead-model coder \
  --ui rich \
  --prompt "..."
```

Modes:

- `--ui auto` — default; use Rich dashboard when available.
- `--ui rich` — require Rich dashboard.
- `--ui plain` — old human summary/trace output only.
- `--ui off` — disable live UI.

Panel size controls:

```bash
--ui-prompt-chars 12000
--ui-answer-chars 16000
```

## Implementation notes

The UI is intentionally presentation-only. OpenHands execution, LangGraph
routing, Team Lead policy, and role reports are unchanged.

The event path is:

```text
OpenHands websocket event
  -> event_callback passed through OpenHandsRoleRunner
  -> RichWorkflowUI.role_event_callback(role)
  -> dashboard last-events deque(maxlen=5)
```

Team Lead direct LLM decisions are also shown, even though they do not have an
OpenHands websocket stream.
