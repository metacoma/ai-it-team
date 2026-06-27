# Stage 24: Rich live websocket events and compact prompt context

v54 refines the Rich UI added in Stage 23.

## Goals

- Show OpenHands websocket events in real time while a role is running.
- Keep only the last five websocket event lines visible to avoid terminal spam.
- Color event lines by type: socket/status/message/action/observation/error.
- Stop rendering full role prompts in the dashboard.
- Render only compact prompt substitutions / context digest: task, repository, Team Lead assignment, workflow step, validation profile, and latest upstream role reports.

## Why full prompts were removed

Role prompts contain long static policy text. Showing them in a live terminal view makes it harder to see what is actually changing between role runs. The UI now shows the dynamic values that were substituted into the prompt while still keeping the full prompt inside the actual OpenHands request.

## CLI flags

Existing flags remain compatible:

```bash
--ui rich
--ui-prompt-chars 6000   # caps compact prompt-context, not the full prompt
--ui-answer-chars 8000
```

## Event styling

The UI classifies compact websocket lines into styles:

- socket: dim/gray
- status/state: blue/dim
- user message: cyan
- assistant message: green
- action/tool: yellow
- observation: magenta
- error/failure: red

The workflow state and JSON output remain unchanged. This is presentation-only.
