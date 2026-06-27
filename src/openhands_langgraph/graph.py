from __future__ import annotations

from typing import Any

from .nodes import (
    architect_node,
    dynamic_role_executor_node,
    coder_node,
    publisher_node,
    qa_node,
    qa_decision_node,
    research_node,
    senior_staff_decision_node,
    senior_staff_engineer_node,
    review_decision_node,
    reviewer_node,
    route_after_qa,
    route_after_review,
    route_after_team_lead,
    route_after_senior_staff,
    route_continue_or_end,
    run_openhands_role_node,
    scout_node,
    team_lead_node,
)
from .state import OpenHandsGraphState


def _state_graph():
    try:
        from langgraph.graph import StateGraph
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise RuntimeError(
            "LangGraph is not installed. Install this package with the 'langgraph' extra."
        ) from exc
    return StateGraph


def build_single_role_graph(**compile_kwargs: Any):
    """Build the Stage 1 MVP graph: START -> run_openhands_role -> END."""
    try:
        from langgraph.graph import END, START
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise RuntimeError(
            "LangGraph is not installed. Install this package with the 'langgraph' extra."
        ) from exc

    graph = _state_graph()(OpenHandsGraphState)
    graph.add_node("run_openhands_role", run_openhands_role_node)
    graph.add_edge(START, "run_openhands_role")
    graph.add_edge("run_openhands_role", END)
    return graph.compile(**compile_kwargs)


def build_development_graph(**compile_kwargs: Any):
    """Build the Stage 2 MVP development workflow.

    Flow:
        START -> scout -> research -> senior_staff_engineer -> senior_staff_decision
              -> architect -> coder -> qa -> reviewer -> review_decision
              -> publisher -> END when QA and reviewer return PASS
              -> END when BLOCKER/unknown/max retries
              -> coder when reviewer returns NEED_FIX and retries remain
    """
    try:
        from langgraph.graph import END, START
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise RuntimeError(
            "LangGraph is not installed. Install this package with the 'langgraph' extra."
        ) from exc

    graph = _state_graph()(OpenHandsGraphState)
    graph.add_node("scout", scout_node)
    graph.add_node("research", research_node)
    graph.add_node("senior_staff_engineer", senior_staff_engineer_node)
    graph.add_node("senior_staff_decision", senior_staff_decision_node)
    graph.add_node("architect", architect_node)
    graph.add_node("coder", coder_node)
    graph.add_node("qa", qa_node)
    graph.add_node("qa_decision", qa_decision_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("review_decision", review_decision_node)
    graph.add_node("publisher", publisher_node)

    graph.add_edge(START, "scout")
    graph.add_conditional_edges("scout", route_continue_or_end("research"), {"research": "research", "end": END})
    graph.add_conditional_edges("research", route_continue_or_end("senior_staff_engineer"), {"senior_staff_engineer": "senior_staff_engineer", "end": END})
    graph.add_edge("senior_staff_engineer", "senior_staff_decision")
    graph.add_conditional_edges("senior_staff_decision", route_after_senior_staff, {"architect": "architect", "end": END})
    graph.add_conditional_edges("architect", route_continue_or_end("coder"), {"coder": "coder", "end": END})
    graph.add_conditional_edges("coder", route_continue_or_end("qa"), {"qa": "qa", "end": END})
    graph.add_edge("qa", "qa_decision")
    graph.add_conditional_edges(
        "qa_decision",
        route_after_qa,
        {
            "coder": "coder",
            "reviewer": "reviewer",
            "end": END,
        },
    )
    graph.add_edge("reviewer", "review_decision")
    graph.add_conditional_edges(
        "review_decision",
        route_after_review,
        {
            "coder": "coder",
            "publisher": "publisher",
            "end": END,
        },
    )
    graph.add_edge("publisher", END)
    return graph.compile(**compile_kwargs)


def build_team_lead_graph(**compile_kwargs: Any):
    """Build v30 Team Lead orchestrated workflow.

    Flow:
        START -> team_lead -> role_executor -> team_lead -> ... -> END

    Team Lead chooses the next role from an allowlist. LangGraph validates the
    decision and reuses one persistent conversation per role_instance while all
    roles operate on the shared workspace.
    """
    try:
        from langgraph.graph import END, START
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise RuntimeError(
            "LangGraph is not installed. Install this package with the 'langgraph' extra."
        ) from exc

    graph = _state_graph()(OpenHandsGraphState)
    graph.add_node("team_lead", team_lead_node)
    graph.add_node("role_executor", dynamic_role_executor_node)

    graph.add_edge(START, "team_lead")
    graph.add_conditional_edges("team_lead", route_after_team_lead, {"role_executor": "role_executor", "end": END})
    graph.add_edge("role_executor", "team_lead")
    return graph.compile(**compile_kwargs)
