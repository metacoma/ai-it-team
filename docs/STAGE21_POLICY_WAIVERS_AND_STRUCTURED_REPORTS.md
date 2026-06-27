# Stage 21 — Policy waivers and richer structured reports

This stage continues the v46 policy-driven Team Lead direction.

## Problem

The workflow still had two structural/policy mismatches:

1. Scout could correctly return `research_domains`, but Team Lead could skip Research and route directly to Senior Staff without explicitly accepting that risk.
2. Senior Staff could produce an exact low-risk fix scope, but LangGraph still hard-blocked Coder unless Architect had produced a PASS plan.

At the same time, roles needed to expose structured data that Team Lead can evaluate without relying on prose summaries.

## Changes

### Research waiver

If the latest Scout PASS report indicates research is needed through any of:

- `research_required=true`
- non-empty `research_domains`
- non-empty `research_questions`

then downstream roles such as Senior Staff, Architect, Coder, QA, Reviewer, and Publisher require one of:

- a Research PASS report, or
- explicit Team Lead waiver:
  - `policy_evaluation.can_skip_research=true`
  - non-empty `policy_evaluation.skip_research_reason`
  - optional but recommended `accepted_report_ids.scout`

LangGraph does not decide whether the waiver is semantically correct. It only checks that skipping Research was deliberate.

### Architect waiver

Architect remains normally required before Coder. Team Lead may skip Architect only with:

- `policy_evaluation.can_skip_architect=true`
- non-empty `policy_evaluation.skip_architect_reason`
- Senior Staff PASS report present
- `accepted_report_ids.senior_staff_engineer` references an existing report

This supports low-risk cases where Senior Staff already provides exact `fix_scope`, `files_to_change`, and `validation_strategy`.

### Structured report improvements

Role reports now expose more routing-critical fields:

- Scout: `research_required`, `research_domains`, `research_questions`, `unknowns`, `validation_questions`, `routing_hints`
- Senior Staff: `root_cause`, `fix_scope`, `files_to_change`, `validation_strategy`, `confidence`, `architect_waiver_candidate`, `routing_hints`
- QA: `targets`, `gaps`, `blocking_gaps`, `required_targets_passed`, `qa_recommendation`

Team Lead sees compact typed report slices in workflow history and should base its subjective policy decisions on these fields.

## Boundary

LangGraph remains a structural safety kernel:

- valid JSON
- known roles/actions
- no accidental publish/complete without explicit policy flags
- no skipped Research/Architect unless Team Lead explicitly issues a waiver

Team Lead owns semantic engineering decisions:

- whether Research may be skipped
- whether Architect may be skipped
- whether QA gaps are blocking
- whether validation is sufficient
- whether PR checks are acceptable
