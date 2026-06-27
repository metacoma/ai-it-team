# Stage 3: Team Lead Orchestrated Workflow

v30 adds a dynamic Team Lead loop on top of the existing OpenHands role runner.

## Model

- LangGraph is the safe executor/state machine.
- Team Lead is a decision maker, not an executor.
- Every role instance gets its own persistent OpenHands conversation.
- Re-running the same role instance sends a follow-up to the existing conversation.
- All role conversations operate on the same mounted workspace/filesystem.
- Docker sandbox images/runtime packages may differ between role conversations.

## Role/session model

Example sessions:

- `team_lead-1` -> one conversation for the whole workflow
- `scout-1` -> one persistent scout conversation
- `research-1` -> one persistent research conversation
- `architect-1` -> one persistent architect conversation
- `coder-1` -> one persistent coder conversation
- `reviewer-1` -> one persistent reviewer conversation
- `publisher-1` -> one persistent publisher conversation

The graph stores `role_sessions` with conversation ids and event ids so follow-up
messages can ignore replayed websocket events.

## Team Lead actions

Allowed actions:

- `RUN_ROLE`
- `RETRY_ROLE`
- `STOP_COMPLETED`
- `STOP_BLOCKED`
- `ASK_HUMAN`

For `RUN_ROLE` and `RETRY_ROLE`, the Team Lead summary JSON must include:

- `next_role`
- `role_instance`
- `context_sources`
- `instructions`
- `reason`

## Safety policy

LangGraph validates Team Lead decisions before execution:

- publisher cannot run before reviewer PASS
- reviewer cannot run before coder result
- coder cannot run before architect plan
- unsupported roles/actions stop as `needs_human_review`
- max Team Lead step limit prevents infinite loops

## CLI

```bash
openhands-graph-run \
  --workflow team-lead \
  --endpoint http://localhost:3000 \
  --model openai/coder \
  --prompt "your task"
```

Useful flags:

```bash
--max-team-lead-steps 12
--output-json
--no-graph-trace
```
