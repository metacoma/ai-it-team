# Stage 14: Retry-aware publisher gates and recovered failure accounting

## Problem

A workflow can contain historical failed attempts followed by successful retries, for example:

```text
qa FAILED missing_assistant_answer
qa NEED_FIX
qa PASS with runtime validation
reviewer PASS
team_lead -> publisher
```

Older failures must remain visible in `role_results`, but they must not remain active blockers after a later successful retry. Publisher gating must also validate the latest accepted QA result and the reviewer result that came after that QA validation, not stale role snapshots.

## v44 behavior

- Runtime errors for a role are removed from the active `errors` list after that same role later succeeds.
- Historical failed attempts remain in `role_results` for auditability.
- The publisher gate checks the latest QA PASS after the latest coder PASS.
- The publisher gate checks a reviewer PASS that happened after the accepted QA PASS.
- Guard errors are split into precise QA-gate and Reviewer-gate reasons.
- Reviewer `validation_review` is still preferred as structured JSON, but explicit prose evidence in the full reviewer report can be conservatively synthesized when the JSON was omitted or lost by summarization.

## Reviewer prose fallback

The fallback is intentionally strict. It only accepts prose that clearly states that the reviewer considered:

- QA build/compile evidence,
- QA test/smoke/integration/runtime evidence,
- non-syntax validation such as runtime, integration, smoke, Xvfb, CI-like, or Freeplane runtime validation,
- and syntax-only validation was not treated as sufficient.

Vague prose such as `looks good` or `diff seems fine` still fails the publisher gate.
