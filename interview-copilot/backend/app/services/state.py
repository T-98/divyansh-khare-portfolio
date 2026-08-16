"""Deterministic InterviewState merge.

State is advanced from the editor's structured `state_delta` plus the router
decision — no extra LLM call is spent on bookkeeping.
"""

from __future__ import annotations

from ..models.interview import InterviewState, StateDelta
from ..models.routing import RoutingDecision

MAX_LIST_ITEMS = 40


def _norm(value: str) -> str:
    return " ".join(value.lower().split())


def merge_list(existing: list[str], additions: list[str]) -> list[str]:
    """Append new items, preserving order, dropping case/whitespace duplicates."""
    seen = {_norm(item) for item in existing}
    merged = list(existing)
    for item in additions:
        cleaned = item.strip()
        if not cleaned:
            continue
        key = _norm(cleaned)
        if key in seen:
            continue
        seen.add(key)
        merged.append(cleaned)
    # Oldest constraints matter least once a session runs long.
    return merged[-MAX_LIST_ITEMS:]


def remove_items(existing: list[str], removals: list[str]) -> list[str]:
    drop = {_norm(item) for item in removals if item.strip()}
    return [item for item in existing if _norm(item) not in drop]


def apply_delta(
    state: InterviewState,
    delta: StateDelta,
    routing: RoutingDecision | None = None,
    *,
    answer_summary: str | None = None,
) -> InterviewState:
    """Return a new state with `delta` folded in. Never mutates the input."""
    updated = state.model_copy(deep=True)

    if delta.current_topic:
        updated.current_topic = delta.current_topic.strip()
    if delta.current_scenario:
        updated.current_scenario = delta.current_scenario.strip()
    if routing is not None:
        updated.current_mode = routing.mode

    updated.established_assumptions = merge_list(
        updated.established_assumptions, delta.new_assumptions
    )
    updated.interviewer_constraints = merge_list(
        updated.interviewer_constraints, delta.new_constraints
    )
    updated.accepted_tradeoffs = merge_list(updated.accepted_tradeoffs, delta.new_tradeoffs)
    updated.systems_mentioned = merge_list(updated.systems_mentioned, delta.new_systems)
    updated.technologies_mentioned = merge_list(
        updated.technologies_mentioned, delta.new_technologies
    )
    updated.source_of_truth_decisions = merge_list(
        updated.source_of_truth_decisions, delta.new_source_of_truth_decisions
    )
    updated.security_boundaries = merge_list(
        updated.security_boundaries, delta.new_security_boundaries
    )
    updated.candidate_claims = merge_list(updated.candidate_claims, delta.new_candidate_claims)

    unresolved = merge_list(updated.unresolved_questions, delta.new_unresolved_questions)
    updated.unresolved_questions = remove_items(unresolved, delta.resolved_questions)

    if delta.candidate_position:
        updated.previous_candidate_position = delta.candidate_position.strip()
    if answer_summary:
        updated.previous_answer_summary = answer_summary.strip()

    return updated


def render_state_for_prompt(state: InterviewState) -> str:
    """Compact human-readable state block for the specialist/editor prompts.

    Empty fields are omitted — an empty section reads to the model as a topic
    worth filling in.
    """
    lines: list[str] = [f"turn_number: {state.turn_number}"]

    def add_scalar(label: str, value: str | None) -> None:
        if value:
            lines.append(f"{label}: {value}")

    def add_list(label: str, values: list[str]) -> None:
        if values:
            lines.append(label + ":")
            lines.extend(f"  - {v}" for v in values)

    add_scalar("current_topic", state.current_topic)
    add_scalar("current_mode", state.current_mode)
    add_scalar("current_scenario", state.current_scenario)
    add_list("interviewer_constraints", state.interviewer_constraints)
    add_list("established_assumptions", state.established_assumptions)
    add_list("accepted_tradeoffs", state.accepted_tradeoffs)
    add_list("source_of_truth_decisions", state.source_of_truth_decisions)
    add_list("security_boundaries", state.security_boundaries)
    add_list("systems_mentioned", state.systems_mentioned)
    add_list("technologies_mentioned", state.technologies_mentioned)
    add_list("unresolved_questions", state.unresolved_questions)
    add_list("candidate_claims", state.candidate_claims)
    add_scalar("previous_candidate_position", state.previous_candidate_position)
    add_scalar("previous_answer_summary", state.previous_answer_summary)

    if len(lines) == 1:
        return "turn_number: 0\n(no prior state — this is the first question)"
    return "\n".join(lines)
