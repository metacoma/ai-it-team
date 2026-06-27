# Stage 4: Role Failure Accounting

v31 makes runtime role failures first-class workflow events.

## Problem

A Team Lead decision such as `RUN_ROLE coder` only means the role was requested. It does not prove that the specialist role completed. If the role runner fails before an assistant answer/summary is produced, downstream roles must not assume the implementation exists.

## Contract

When a specialist role fails at runtime, the LangGraph layer now appends a synthetic failed role result to `role_results`:

- `status: failed`
- `ok: false`
- `summary_action: FAILED`
- `blocking: true`
- `error_type`
- `retryable`
- `metrics`

The Team Lead prompt separates:

- successful specialist results
- failed specialist attempts
- requested roles without specialist result
- previous Team Lead decisions

## Retry policy

If the latest specialist role failed and is retryable, Team Lead should prefer:

- `RETRY_ROLE` for the same `role_instance`, or
- `ASK_HUMAN` / `STOP_BLOCKED` if retry is unsafe.

Reviewer is only allowed after a usable coder result with `ok=true`. Publisher is only allowed after reviewer PASS.

## Common failure types

- `llm_tool_call_json_parse_error`
- `missing_assistant_answer`
- `openhands_transport_error`
- `summary_json_parse_error`
- `role_runtime_error`
