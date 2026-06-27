# Stage 2: Linear Development Graph

Stage 2 adds the first senior-assistant workflow on top of the Stage 0 OpenHands SDK and Stage 1 single-role LangGraph primitive.

## Goal

Prove the core multi-role loop:

```text
scout -> research -> senior_staff_engineer -> architect -> coder -> reviewer -> publisher -> PR
```

The graph, not a free-form LLM, controls role ordering. LLM roles only return structured summaries and actions. LangGraph reads those summaries and deterministically routes the next step.

## Workflow

```text
START
  -> scout
  -> research
  -> senior_staff_engineer
  -> senior_staff_decision
      PROCEED   -> architect
      NEED_MORE_RESEARCH / NEED_MORE_SCOUT / ASK_HUMAN -> END needs_human_review
      BLOCKER   -> END blocked
  -> architect
  -> coder
  -> reviewer
  -> review_decision
      PASS      -> publisher
      NEED_FIX  -> coder retry, while retries remain
      BLOCKER   -> END blocked
      unknown   -> END needs_human_review
  -> publisher
      pushes branch and creates PR with gh + GITHUB_TOKEN
  -> END completed/publish_blocked
```

`max_fix_iterations` limits the `coder -> reviewer` retry loop.

## v28 research gate

Stage 2 now includes a dedicated `research` role between `scout` and `architect`. Scout does not need task-specific hard-coded best practices in its prompt. Instead, Scout reports target runtime/tooling domains that require external research, such as CI providers, packaging systems, GUI/display runtimes, filesystem/permissions, secrets/auth, publishing APIs, network/service lifecycle, caches/artifacts, or language/framework conventions.

Research consumes those domains and produces a concise Research Brief with external environment contracts, portability risks, validation implications, and recommendations for Architect. Architect must then reconcile Scout's repository facts with Research's external constraints before producing the coder plan.


## v29 Senior Staff execution strategy gate

Stage 2 now includes a `senior_staff_engineer` role between `research` and `architect`. This role is a read-only strategy gate, not an executor. It consumes the full Scout report and Research brief, then produces a Senior Staff Engineering Strategy containing:

- target runtime contract
- assumption ledger
- cheap preflight checks
- expensive validation strategy
- risk assessment
- constraints for architect/coder/reviewer/publisher
- stop conditions

The purpose is to prevent hidden assumptions from moving across execution environments. For example, OpenHands sandbox paths, permissions, or installed tools must not be assumed to exist in CI runners, Kubernetes pods, baremetal hosts, containers, GitOps controllers, or remote machines unless the plan includes evidence and preflight checks.

LangGraph owns routing after this role. `PROCEED` routes to Architect. `NEED_MORE_RESEARCH`, `NEED_MORE_SCOUT`, and `ASK_HUMAN` stop as `needs_human_review`. `BLOCKER` stops as `blocked`.

Roles that may execute or publish (`coder`, `reviewer`, `publisher`) are explicitly told that the OpenHands runtime is a Docker sandbox based on Debian Trixie. If installing an OS package is necessary and safe for that role, they must use `sudo`, for example `sudo apt-get update && sudo apt-get install -y <package>`. Read-only/planning roles (`scout`, `research`, `senior_staff_engineer`, `architect`) must not install packages or run validation commands.

## Role prompts

Prompts are generated in `openhands_langgraph.prompts` and are intentionally role-specific:

- `scout`: factual repository investigation only; read-only discovery; must not run tests/builds/installers; must identify external research domains triggered by the task/repository evidence.
- `research`: external best-practices/runtime investigation only; consumes scout research domains and produces environment/tooling contracts for architect.
- `senior_staff_engineer`: senior execution strategy gate only; read-only; produces target runtime contract, assumption ledger, preflight checks, validation strategy, and constraints.
- `architect`: implementation plan only; read-only planning; must not run tests/builds/installers; must reconcile scout repository facts, research constraints, and Senior Staff execution contract before writing the plan.
- `coder`: focused implementation only; may change files and run validation.
- `reviewer`: independent quality gate only; receives the architect plan and coder summary, then independently inspects repository/diff/validation evidence. It does not receive the full coder report as trusted context.
- `publisher`: final publishing role only; inspects changes, pushes a branch, and creates a GitHub PR using `gh` and `GITHUB_TOKEN`.

Every development prompt includes:

- original user task
- repository/workspace context without hard-coded checkout paths
- role responsibility
- hard “do not” boundaries
- expected output format
- full upstream role answers where needed for task quality: scout → research, scout+research → architect, and architect → coder/reviewer
- compact routing/status summaries where needed for control handoff, especially coder → reviewer and reviewer → publisher

Repository prompts intentionally do **not** force a checkout path. OpenHands can provide repository context through `selected_repository`, an existing sandbox, a mounted workspace, or no repository at all. Roles are instructed to use the workspace OpenHands provides and to report a blocker when required repository access is unavailable.

`summary_json` is used for deterministic LangGraph routing. It is not used as a replacement for important upstream artifacts: the research role receives the full scout answer as a plain artifact block, the architect receives the full scout answer plus full research brief as plain artifact blocks, the coder receives the full architect plan as a plain artifact block, and the reviewer receives the full architect plan plus only the coder summary. The reviewer must inspect the actual repository/diff/workspace state independently instead of relying on the coder's full report. The prompts intentionally do not embed the entire `RoleRunResult` JSON, because that duplicates summaries and pollutes the working context.

## Summary actions

The reviewer summary must set `action` to exactly one of:

```text
PASS
NEED_FIX
BLOCKER
```

Routing is deterministic:

- reviewer `PASS` routes to publisher
- publisher `PASS` ends as `completed`
- reviewer `NEED_FIX` retries coder until `max_fix_iterations`
- `BLOCKER` ends as `blocked`
- anything ambiguous ends as `needs_human_review`

## CLI

```bash
openhands-graph-run \
  --workflow development \
  --endpoint http://localhost:3000 \
  --model openai/coder \
  --repository metacoma/freeplane_plugin_grpc \
  --git-provider github \
  --prompt "добавь Ruby gRPC client"
```

By default the graph CLI prints a readable colored role trace and final summary. It shows what each role receives as a short digest, never the full prompt. Use `--output-json` for the complete JSON graph state.

Useful controls:

```bash
--max-fix-iterations 2
--show-events
--raw-websocket
--websocket-retry-seconds 240
--output-json
--no-color
--no-graph-trace
```

## Done criteria

Stage 2 is considered complete when:

- development graph exists as `build_development_graph()`
- CLI supports `--workflow development`
- prompts are role-specific and include strong boundaries
- reviewer `PASS` routes to publisher
- reviewer `NEED_FIX` retries coder
- retry loop is bounded by `max_fix_iterations`
- reviewer `BLOCKER` stops the graph
- publisher receives architect plan and reviewer summary
- publisher prompt requires `gh` + `GITHUB_TOKEN` for PR creation
- tests cover all routing outcomes
- scout prompt requires research domains for external best-practice/runtime investigation
- research prompt produces a research brief with environment contracts and portability risks
- architect prompt consumes the research brief and reconciles it with scout facts
- scout/architect/research prompts explicitly forbid test/build/validation execution
- CLI has readable colored trace output and `--output-json` compatibility mode

## Stage 2.1: Human-readable metrics

`openhands-graph-run` prints a compact metrics block after a workflow finishes.
The metrics are intentionally screen-only for now; no database or JSONL sink is
introduced yet.

Displayed workflow metrics:

- total workflow duration
- number of executed roles
- total summary attempts
- coder fix iteration counter
- action counts
- start/finish window

Displayed per-role metrics:

- role duration
- summary attempts
- answer size in characters
- conversation id
- action/risk/blocking/summary

The same data is included in `workflow_metrics` and per-role `metrics` when
`--output-json` is used.
