# Stage 1: Minimal LangGraph integration

Stage 1 proves the core control-plane loop:

```text
LangGraph node
  -> OpenHandsRoleRunner.run_role()
  -> RoleRunResult / RoleSummary
  -> JSON-safe GraphState update
```

It intentionally does not implement a full senior/staff workflow yet. No
parallel architects, gates, metrics store, approval, GitOps or infra workflow
are included in this stage.

## Public module

```python
from openhands import OpenHandsInstance, OpenHandsRoleRunner
from openhands_langgraph import build_single_role_graph

instance = OpenHandsInstance("http://localhost:3000", default_model="openai/coder")
runner = OpenHandsRoleRunner(instance)
graph = build_single_role_graph()

result = await graph.ainvoke(
    {
        "user_task": "study repo",
        "role": "scout",
        "repository": "metacoma/freeplane_plugin_grpc",
    },
    config={"configurable": {"openhands_runner": runner}},
)
```

## State contract

Runtime objects must be passed through LangGraph config, not stored in state.
State remains JSON-safe and can be checkpointed.

Input fields:

- `user_task` or `prompt`
- `role`
- `role_instance`
- `model`
- `repository`
- `branch`
- `git_provider`
- `sandbox_id`
- `conversation_id`
- `title`
- `extra_payload`
- `conversation_params`
- `role_run_options`

Output fields:

- `role_results`
- `last_role_result`
- `final_answer`
- `final_status`
- `errors`

## Done criteria

- Single-role LangGraph workflow can run against OpenHands.
- `OpenHandsRoleRunner` remains the only component that knows about summary
  retry, same-conversation follow-up and OpenHands WebSocket details.
- Node errors are returned in graph state instead of producing raw tracebacks.
- LangGraph is an optional dependency exposed through the `langgraph` extra.
