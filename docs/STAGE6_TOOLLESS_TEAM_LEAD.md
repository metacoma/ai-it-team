# Stage 6: Tool-less Team Lead

This release is based on the v31 failure-accounting model and changes only the Team Lead execution path.

## Problem

Running Team Lead as an OpenHands conversation is unsafe for orchestration: even with prompts that say "do not execute", the OpenHands agent still has agent-runtime behavior and may inspect files, call task tracking tools, or perform scout-like work. That can make it claim a specialist phase is complete even when no specialist result exists.

## Change

Team Lead is no longer run through OpenHandsRoleRunner.

Instead, Team Lead uses a direct OpenAI-compatible chat completion call:

```text
LangGraph state -> direct LLM -> TeamLeadDecision JSON -> Pydantic validation -> LangGraph executor
```

Specialist roles still run through OpenHands and keep persistent role conversations.

## Required configuration

For `--workflow team-lead`, provide a direct LLM endpoint:

```bash
openhands-graph-run \
  --workflow team-lead \
  --endpoint http://localhost:3000 \
  --model openai/coder \
  --team-lead-base-url http://LLM_SERVER:4000/v1 \
  --team-lead-model openai/coder \
  --prompt "..."
```

Environment variables are also supported:

```text
TEAM_LEAD_BASE_URL / OPENAI_BASE_URL / LLM_BASE_URL / LITELLM_BASE_URL
TEAM_LEAD_API_KEY / OPENAI_API_KEY / LLM_API_KEY / LITELLM_API_KEY
TEAM_LEAD_MODEL
```

## Safety model

Team Lead has no tools, no shell, no browser, no filesystem, and no OpenHands sandbox. It can only return a JSON routing decision. LangGraph still validates the decision before launching any specialist role.
