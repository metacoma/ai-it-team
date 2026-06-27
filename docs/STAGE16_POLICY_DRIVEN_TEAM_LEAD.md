# Stage 16: Policy-driven Team Lead and typed role reports

v46 moves semantic delivery decisions out of LangGraph guards and into the tool-less Team Lead decision prompt.

## Problem

Earlier stages accumulated domain-specific guards in Python code, such as blocking specific phrases about Ruby, Xvfb, Freeplane, CI-only validation, or missing runtime tools. These checks solved concrete failures but made LangGraph behave like a second Team Lead and made the workflow hard to generalize across repositories.

## New boundary

LangGraph is now a minimal safety kernel:

- validate Team Lead JSON shape;
- validate known actions and known roles;
- prevent unsafe recovery after failed specialist attempts;
- enforce basic role sequence invariants such as coder before QA, QA before reviewer, reviewer before publisher;
- require explicit `policy_evaluation.can_publish=true` before publisher;
- validate that referenced report IDs exist when Team Lead provides them.

Team Lead owns semantic delivery policy:

- decide whether QA validation is sufficient;
- decide whether validation gaps are blocking or accepted risks;
- decide whether reviewer evidence is sufficient;
- decide whether publishing is safe;
- decide whether to retry QA, retry coder, route to reviewer, publish, ask human, or stop blocked.

## Typed role reports

Specialist prompts now ask roles to finish with a `FINAL_ROLE_REPORT_JSON` footer. This footer is parsed into `role_report` and passed to Team Lead in compact history.

Examples:

- QA returns validation targets, gaps, commands, environment reconstruction, and recommendation.
- Reviewer returns diff/QA evidence review, lint/static checks, findings, required fixes, and publisher readiness.
- Coder returns change_set_id, changed files, implementation summary, and self-validation.
- Scout returns facts only, not hypotheses.

The parser is tolerant and keeps compatibility with older summaries. If a role omits the explicit footer, LangGraph creates a `summary_compat` role report from the existing role summary.

## Team Lead decision

The direct LLM Team Lead decision now supports:

```json
{
  "accepted_report_ids": {
    "coder": "coder-1:...",
    "qa": "qa-1:...",
    "reviewer": "reviewer-1:..."
  },
  "policy_evaluation": {
    "can_review": true,
    "can_publish": true,
    "qa_evidence_accepted": true,
    "reviewer_evidence_accepted": true,
    "blocking_reasons": [],
    "accepted_risks": []
  }
}
```

`can_publish=true` is required for publisher. LangGraph does not decide whether Ruby/Xvfb/CI gaps are acceptable; it requires Team Lead to make that decision explicitly.
