# Stage 7: QA validation gate

v37 adds an explicit QA role between Coder and Reviewer.

## Development flow

```text
scout
  -> research
  -> senior_staff_engineer
  -> architect
  -> coder
  -> qa
  -> reviewer
  -> publisher
```

## Responsibilities

- Coder implements the architect plan and must install needed tools, compile/build the changed area, and run targeted validation before handing off.
- QA validates the shared workspace after coder. QA must install all required utilities for compilation/test execution when reasonable and safe, using `sudo` for Debian Trixie OS packages.
- Reviewer independently reviews code/diff and QA evidence. Reviewer must install required linters/static checkers for changed file types when reasonable and safe, using `sudo` for Debian Trixie OS packages.
- Publisher can publish only after QA PASS and Reviewer PASS.

## Environment contract

OpenHands roles run in Docker sandboxes based on Debian Trixie. The workspace filesystem is shared across role conversations, but packages installed in one role container must not be assumed to exist in another role container.

Writer/validator/reviewer roles must not skip required compilation/tests merely because a tool is missing. They should install missing reasonable tools and report every install command.

## Routing rules

- Coder PASS routes to QA.
- QA PASS routes to Reviewer.
- QA NEED_FIX routes back to Coder, subject to `max_fix_iterations`.
- QA BLOCKER stops the workflow.
- Reviewer PASS routes to Publisher.
- Publisher requires both QA PASS and Reviewer PASS in Team Lead workflow.
