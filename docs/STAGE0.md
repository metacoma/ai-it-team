# Stage 0: OpenHands SDK baseline

Stage 0 is the transport/SDK baseline used by future LangGraph workflows.

## Public contract

The package exposes a small SDK layer:

- `OpenHandsInstance` — one OpenHands endpoint/app-server.
- `OpenHandsConversation` — one OpenHands conversation/sandbox.
- `OpenHandsRoleRunner` — role abstraction: main answer + same-conversation JSON summary.
- `RoleRunSpec` — validated role input contract.
- `RoleRunResult` — validated role output contract.
- `RoleSummary` — validated LLM summary contract.

## Invariants

- The client does not read or write `/api/settings`.
- Conversation creation uses `POST /api/v1/app-conversations`.
- Only explicitly provided app-conversation fields are sent.
- `llm_model` is a per-conversation field only.
- Summary is sent as a follow-up message to the same conversation/sandbox.
- Summary does not create a second sandbox.
- WebSocket startup failures are retried before failing.
- Raw OpenHands REST/WebSocket events stay tolerant `dict` payloads.
- Public SDK contracts are Pydantic models.

## Pydantic contract layer

The trusted boundary for LangGraph is Pydantic:

- `RoleRunSpec`
- `RoleSummary`
- `SummaryAttempt`
- `AppConversationStart`
- `OpenHandsRunResult`
- `RoleRunResult`

Use `model_dump(mode="json")` for direct model serialization or `to_dict()` for compatibility output used by the CLI and future graph state.

`session_api_key` is excluded from normal dumps. Raw OpenHands payloads are only included when explicitly requested through compatible helper methods.

## LangGraph-safe result

`RoleRunResult.to_dict(include_answer=False, include_raw_summary=False)` returns a compact state-safe dictionary containing:

- role metadata
- conversation id
- status
- summary object
- summary action/risk/blocking fields
- summary attempt metadata
- answer-run metadata without the full answer text

This is the expected object shape for future LangGraph state.
