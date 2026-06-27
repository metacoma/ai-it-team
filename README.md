# openhands-ws-cli

Small Python package and CLI for starting OpenHands V1 app conversations and waiting for the final assistant answer.

The CLI does **not** read or write `/api/settings`. It sends only the fields explicitly provided by the user to `POST /api/v1/app-conversations`.

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

## Quiet default output

By default, events are hidden. The command waits until the conversation reaches a terminal execution status and prints only the final assistant answer to stdout.

```bash
openhands-watch   --endpoint http://localhost:3000   --prompt "изучи репозиторий metacoma/freeplane_plugin_grpc"   --model openai/coder
```

## Explicit-only payload behavior

No conversation/sandbox field is sent unless you specify it using a CLI flag or JSON payload.

For example, this sends only `initial_message`, `llm_model`, `selected_repository`, and `git_provider`:

```bash
openhands-watch   --endpoint http://localhost:3000   --prompt "изучи репозиторий"   --model openai/coder   --repository metacoma/freeplane_plugin_grpc   --git-provider github
```

Preview the exact payload, with secrets redacted:

```bash
openhands-watch   --endpoint http://localhost:3000   --prompt "hello"   --model openai/coder   --secret GITHUB_TOKEN=xxx   --print-payload
```

## Supported AppConversationStartRequest fields

Convenience flags exist for the known V1 fields:

```text
--sandbox-id
--conversation-id
--prompt / --initial-message-json / --initial-message-file
--system-message-suffix
--processors-json / --processors-file
--model                         -> llm_model
--repository                    -> selected_repository
--branch                        -> selected_branch
--git-provider
--suggested-task-json / --suggested-task-file
--title
--trigger
--pr-number                     repeatable
--parent-conversation-id
--agent-type                    default|plan
--public / --private
--plugins-json / --plugins-file / --plugin-json
--secrets-json / --secrets-file / --secret
```

## Escape hatch for new or unsupported fields

Use a complete base payload:

```bash
openhands-watch   --endpoint http://localhost:3000   --payload-file payload.json
```

Or set arbitrary top-level fields:

```bash
openhands-watch   --endpoint http://localhost:3000   --prompt "hello"   --param-json 'tags={"role":"scout"}'   --param-json 'custom_field=true'
```

Merge order:

```text
--payload-file
--payload-json
--param-json
known CLI flags
```

Later layers override earlier ones.

## Event output modes

```bash
openhands-watch ... --show-events     # compact trace
openhands-watch ... --debug-events    # compact trace + state/stat summaries
openhands-watch ... --raw-events      # full JSON events
openhands-watch ... --raw-websocket   # print websocket connection attempts to stderr
```

## Role abstraction: answer + validated JSON summary

`openhands-role` is a higher-level command for role-style pipelines:

1. Start the main OpenHands conversation from the explicit payload fields you pass.
2. Wait for the final assistant answer.
3. Send the summary prompt into the same existing agent-server conversation with `POST /api/conversations/{conversation_id}/events`.
4. Re-run the agent in that same conversation, without creating a new sandbox.
5. Validate the summary with Python `json.loads`.
6. If the summary is not valid JSON, send a correction prompt into the same conversation with the parser error and previous invalid response.
7. Repeat until valid JSON is returned, then print both the full answer and the summary JSON.

Default use:

```bash
openhands-role \
  --endpoint http://localhost:3000 \
  --prompt "изучи репозиторий metacoma/freeplane_plugin_grpc" \
  --model openai/coder
```

Default output:

```text
========== OpenHands answer ==========
<full role answer>
========== OpenHands summary JSON ==========
{
  "action": null,
  "blocking": false,
  "blocking_summary": [],
  "risk_level": null,
  "status": "completed",
  "summary": "...",
  "valid": true
}
========== end ==========
```

Machine-readable combined output:

```bash
openhands-role ... --output-json
```

Save artifacts:

```bash
openhands-role ... \
  --answer-file answer.md \
  --summary-file summary.json
```

Show summary retry attempts and JSON parser errors:

```bash
openhands-role ... --summary-show-attempts
```

Limit summary retries instead of retrying forever:

```bash
openhands-role ... --summary-max-attempts 5
```

`--summary-model` is accepted for compatibility but ignored in the default same-conversation summary mode, because OpenHands does not switch `llm_model` after the conversation has already started.

Use custom JSON schema/instructions:

```bash
openhands-role ... --summary-instructions-file summary_prompt.txt
```

Important: summary no longer starts a second app conversation. It uses the already-created conversation/sandbox and sends follow-up messages to its agent-server `/events` endpoint with `run=true`.

## Final answer extraction behavior

Some OpenHands builds emit `execution_status=finished` before the final assistant `MessageEvent`, or expose the UI-visible answer through a finish-like action / REST history instead of a plain chat message event. This client handles that by:

1. collecting assistant text from `MessageEvent` and finish-like `ActionEvent` shapes;
2. after terminal status, waiting briefly for a late final answer event;
3. if still empty, trying agent-server REST history/state endpoints as a fallback.

Tune the grace window if needed:

```bash
openhands-role ... --terminal-grace-seconds 30
openhands-watch ... --terminal-grace-seconds 30
```


## v11 reliability notes

This build treats transient start-task polling timeouts as retryable, tries the next websocket URL when a candidate closes with code 4001, and uses REST final-answer fallback instead of printing raw Python tracebacks.

## Tests

The package includes an in-process fake OpenHands test stack:

- `aiohttp` mock app-server for `POST /api/v1/app-conversations`, start-task polling, app-conversation metadata, and follow-up `POST /api/conversations/{conversation_id}/events`.
- `aiohttp` WebSocket endpoint for `/sockets/events/{conversation_id}`.
- Tests assert that `openhands-role` creates only one app-conversation and sends JSON-summary retries back into the same existing conversation instead of creating a second sandbox.

Run tests:

```bash
pip install -e '.[test]'
pytest -q
```



## v28 development workflow update

The development LangGraph workflow now includes an explicit `research` role between `scout` and `architect`:

```text
scout -> research -> architect -> coder -> reviewer -> publisher
```

Scout reports repository facts and identifies external research domains. Research turns those domains into best-practice/runtime contracts. Architect consumes both artifacts before producing the implementation plan. This is intended to catch target-environment mismatches, such as local sandbox paths leaking into GitHub Actions workflows, without adding task-specific hard-codes to prompts.

## Stage 0 status

This package now contains the Stage 0 OpenHands SDK baseline for later LangGraph integration. The contract and invariants are documented in [`docs/STAGE0.md`](docs/STAGE0.md).

## SDK layer for LangGraph / orchestrators

The CLI is now a thin wrapper over a small SDK-like OpenHands layer:

```text
OpenHandsInstance       # one OpenHands endpoint/app-server
OpenHandsConversation   # one concrete conversation/sandbox
OpenHandsRoleRunner     # role = task answer + same-conversation JSON summary
RoleRunSpec             # serializable-ish role run input for fan-out
RoleRunResult           # full answer + parsed summary + metadata
```

Minimal use:

```python
from openhands import OpenHandsInstance, OpenHandsRoleRunner

instance = OpenHandsInstance(
    endpoint="http://localhost:3000",
    default_model="openai/coder",
)
runner = OpenHandsRoleRunner(instance)

result = await runner.run_role(
    role="scout",
    prompt="изучи репозиторий metacoma/freeplane_plugin_grpc",
    repository="metacoma/freeplane_plugin_grpc",
    git_provider="github",
)

print(result.answer)
print(result.summary_json)
print(result.conversation_id)
```

Follow-up messages use the same sandbox/conversation:

```python
conversation = await instance.create_conversation(
    prompt="изучи репозиторий",
    repository="metacoma/freeplane_plugin_grpc",
    git_provider="github",
)
main = await conversation.wait_finished()
summary = await conversation.send_message("Return a JSON summary only", known_event_ids=main.seen_event_ids)
```

Fan-out/fan-in orchestration can use `RoleRunSpec`:

```python
from openhands import RoleRunSpec

results = await runner.run_roles_parallel(
    [
        RoleRunSpec(role="architect", role_instance="architect_A", prompt="minimal safe plan"),
        RoleRunSpec(role="architect", role_instance="architect_B", prompt="critical risk-focused plan"),
    ],
    max_concurrency=2,
)
```

For LangGraph, store only serializable fields from `result.to_dict()` in graph state; keep `OpenHandsInstance` / `OpenHandsRoleRunner` in runtime config/dependencies rather than inside state.

## SDK contracts

As of v0.11.0, public SDK result/spec/summary objects are Pydantic v2 models. Raw OpenHands events remain tolerant dictionaries, but objects intended for LangGraph state can be serialized with `model_dump(mode="json")` or compatibility `to_dict()` helpers.

## Stage 1 LangGraph MVP

As of v0.12.0, LangGraph support is available as an optional integration layer.
Install it explicitly:

```bash
pip install -e '.[langgraph]'
```

The first graph is intentionally tiny:

```text
START -> run_openhands_role -> END
```

Minimal use:

```python
from openhands import OpenHandsInstance, OpenHandsRoleRunner
from openhands_langgraph import build_single_role_graph

instance = OpenHandsInstance("http://localhost:3000", default_model="openai/coder")
runner = OpenHandsRoleRunner(instance)
graph = build_single_role_graph()

result = await graph.ainvoke(
    {
        "user_task": "изучи репозиторий metacoma/freeplane_plugin_grpc",
        "role": "scout",
        "repository": "metacoma/freeplane_plugin_grpc",
        "git_provider": "github",
    },
    config={"configurable": {"openhands_runner": runner}},
)
```

CLI wrapper:

```bash
openhands-graph-run \
  --endpoint http://localhost:3000 \
  --model openai/coder \
  --role scout \
  --prompt "изучи репозиторий metacoma/freeplane_plugin_grpc"
```

Stage 1 details are documented in [`docs/STAGE1.md`](docs/STAGE1.md).

Run full tests including LangGraph:

```bash
pip install -e '.[test,langgraph]'
pytest -q
```


## LangGraph development workflow

Install the optional LangGraph extra:

```bash
pip install -e '.[langgraph]'
```

Run the Stage 2 linear development workflow:

```bash
openhands-graph-run   --workflow development   --endpoint http://localhost:3000   --model openai/coder   --repository metacoma/freeplane_plugin_grpc   --git-provider github   --prompt "добавь Ruby gRPC client"
```

The Stage 2 workflow is deterministic:

```text
scout -> research -> architect -> coder -> reviewer -> review_decision
```

Reviewer routing:

```text
PASS     -> completed
NEED_FIX -> coder retry, limited by --max-fix-iterations
BLOCKER  -> blocked
unknown  -> needs_human_review
```

Role ordering is controlled by LangGraph. LLM roles only produce answers and validated JSON summaries. Scout produces repository facts plus research domains; Research turns those domains into an external best-practices/runtime brief; Architect consumes both artifacts. Downstream prompts receive upstream answers as plain artifact blocks, not as full `RoleRunResult` JSON; compact summaries are included once for routing/status context.


## v39 validation environment reconstruction

See `docs/STAGE9_VALIDATION_ENVIRONMENT_RECONSTRUCTION.md` for the QA/Reviewer contract that treats missing upstream source trees, sibling checkout layouts, generated sources, Xvfb/GUI runtimes, and other documented build dependencies as validation setup tasks rather than excuses for syntax-only validation.

## Stage 10: Scout facts-only mode

The Team Lead workflow now treats `scout` as a facts-only context discovery role. Scout must not propose root-cause hypotheses, candidate causes, or diagnostic conclusions. It reports exact CI/log evidence, relevant files, documented validation commands, research domains, risks, unknowns, and validation questions. Root-cause reasoning is left to Senior Staff, Architect, Coder, QA, and Reviewer after Scout has supplied factual context.
# ai-it-team
