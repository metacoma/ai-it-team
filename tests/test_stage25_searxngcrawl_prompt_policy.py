from __future__ import annotations

from openhands_langgraph.prompts import build_role_prompt, build_role_summary_instructions


def _state() -> dict:
    return {
        "user_task": "Add a GitLab CI component include using current GitLab CI syntax",
        "repository": "metacoma/ai-it-team",
        "team_lead_decision": {
            "action": "RUN_ROLE",
            "next_role": "research",
            "role_instance": "research-1",
            "instructions": "Use local-docs MCP/searxNcrawl for current docs.",
        },
    }


def test_research_prompt_requires_bounded_searxncrawl_docs_lookup() -> None:
    prompt = build_role_prompt("research", _state())
    assert "local-docs MCP" in prompt
    assert "searxNcrawl" in prompt or "searxncrawl" in prompt.lower()
    assert "search first" in prompt
    assert "crawl only that single page" in prompt or "crawl one official" in prompt
    assert "Do not use crawl_site" in prompt
    assert "official/current" in prompt


def test_coder_prompt_requires_docs_lookup_for_external_syntax() -> None:
    prompt = build_role_prompt("coder", _state())
    assert "local-docs MCP" in prompt
    assert "GitHub Actions" in prompt
    assert "GitLab CI" in prompt
    assert "CLI flags" in prompt
    assert "If local-docs/search/crawl is unavailable" in prompt


def test_reviewer_prompt_verifies_external_behavior_with_docs_when_needed() -> None:
    prompt = build_role_prompt("reviewer", _state())
    assert "local-docs MCP" in prompt
    assert "Include the documentation URLs" in prompt
    assert "Do not repeat live lookups" in prompt


def test_team_lead_prompt_routes_external_docs_to_research() -> None:
    prompt = build_role_prompt("team_lead", _state())
    assert "Current-docs routing policy" in prompt
    assert "normally route Research before implementation" in prompt
    assert "crawl one official page" in prompt


def test_summary_json_contract_exposes_docs_sources() -> None:
    research = build_role_summary_instructions("research")
    coder = build_role_summary_instructions("coder")
    reviewer = build_role_summary_instructions("reviewer")
    assert "docs_sources" in research
    assert "docs_lookup_used" in research
    assert "current_docs_confidence" in research
    assert "docs_sources" in coder
    assert "docs_verification_used" in reviewer


def test_prompt_policy_does_not_use_workspace_ai_handoff_files() -> None:
    for role in ("research", "architect", "coder", "qa", "reviewer", "publisher"):
        prompt = build_role_prompt(role, _state())
        assert "/workspace/ai" not in prompt
        assert "docs_context_pack" not in prompt
