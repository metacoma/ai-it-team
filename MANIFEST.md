# ai-it-team searxNcrawl prompt MVP

This tarball contains complete replacement files, not a patcher.

## Files

- `src/openhands_langgraph/prompts.py`
  - Full prompt module with searxNcrawl/local-docs MCP policy embedded directly.
  - No `/workspace/ai` handoff files.
  - No `docs_context_pack` workflow.
  - Research/Coder/Reviewer/Team Lead are instructed to use bounded current-docs lookups when external/current API/spec/config behavior matters.

- `tests/test_stage25_searxngcrawl_prompt_policy.py`
  - Regression tests for the prompt policy.

## Apply

From repository root:

```bash
tar -xzf ai-it-team-searxncrawl-full-files.tar.gz -C .
python3 -m compileall -q src tests
pytest -q tests/test_stage25_searxngcrawl_prompt_policy.py
```

## Runtime assumption

OpenHands has an MCP server named/recognizable as `local-docs`, backed by searxNcrawl, exposing search/crawl tools.

Expected role behavior:

1. Search first.
2. Use at most 3 search results.
3. Crawl one official/current page.
4. Avoid `crawl_site` unless Team Lead explicitly requests broad research.
5. Cite used documentation URLs in role reports/summaries.
