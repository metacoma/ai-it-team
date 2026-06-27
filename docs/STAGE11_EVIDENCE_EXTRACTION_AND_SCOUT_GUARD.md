# Stage 11: Evidence Extraction and Scout Facts-Only Guard

v41 fixes two orchestration failure modes observed in the Team Lead workflow.

## 1. QA / Reviewer evidence may live in the full answer, not the compact summary

OpenHands roles produce a full answer and then a separate compact JSON summary. Local
models may correctly include the required `validation` / `validation_review` JSON in
the full role answer but omit it from the compact summary. v39/v40 guards only read
the compact summary, so a valid QA PASS could be rejected as if no build/test evidence
existed.

v41 makes routing guards inspect both places:

- `summary.validation`
- `answer` embedded JSON object with key `validation`
- `summary.validation_review`
- `answer` embedded JSON object with key `validation_review`

When a role result is post-processed, LangGraph also copies answer-level evidence into
the summary object so later Team Lead decisions see the same evidence.

## 2. Scout must remain facts-only

Scout is a read-only context-gathering role. It must not provide root-cause hypotheses
or diagnostic conclusions. v40 normalized Team Lead instructions before launching
Scout, but Scout or the summary step could still output diagnostic wording.

v41 adds post-role enforcement:

- If forbidden diagnostic wording appears only in the compact Scout summary, the
  summary is sanitized.
- If forbidden diagnostic wording appears in the full Scout answer, the Scout result is
  marked `NEED_FIX` / not usable, so downstream roles cannot treat it as a valid context
  artifact.

This prevents Team Lead / Senior Staff / Architect from consuming Scout conclusions as
if they were established facts.
