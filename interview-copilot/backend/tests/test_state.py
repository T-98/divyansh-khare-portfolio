"""Structured state merge and prompt rendering."""

from __future__ import annotations

from app.models.interview import InterviewState, StateDelta
from app.services.state import apply_delta, merge_list, remove_items, render_state_for_prompt
from tests.conftest import make_routing


def test_merge_list_appends_and_preserves_order():
    assert merge_list(["a"], ["b", "c"]) == ["a", "b", "c"]


def test_merge_list_deduplicates_case_and_whitespace_insensitively():
    assert merge_list(["No idempotency"], ["  no   idempotency  ", "new one"]) == [
        "No idempotency",
        "new one",
    ]


def test_merge_list_ignores_blanks():
    assert merge_list([], ["  ", ""]) == []


def test_remove_items_is_case_insensitive():
    assert remove_items(["Keep", "Drop"], ["drop"]) == ["Keep"]


def test_apply_delta_does_not_mutate_the_input():
    state = InterviewState(session_id="s", interviewer_constraints=["one"])
    apply_delta(state, StateDelta(new_constraints=["two"]))
    assert state.interviewer_constraints == ["one"]


def test_apply_delta_accumulates_constraints_across_turns():
    state = InterviewState(session_id="s")
    state = apply_delta(state, StateDelta(new_constraints=["booking POST timed out"]))
    state = apply_delta(state, StateDelta(new_constraints=["no idempotency support"]))
    state = apply_delta(state, StateDelta(new_constraints=["cannot query afterwards"]))
    assert state.interviewer_constraints == [
        "booking POST timed out",
        "no idempotency support",
        "cannot query afterwards",
    ]


def test_apply_delta_records_mode_from_routing():
    state = apply_delta(
        InterviewState(session_id="s"), StateDelta(), make_routing(mode="incident")
    )
    assert state.current_mode == "incident"


def test_apply_delta_resolves_questions():
    state = InterviewState(session_id="s", unresolved_questions=["does it support idempotency"])
    merged = apply_delta(
        state, StateDelta(resolved_questions=["does it support idempotency"])
    )
    assert merged.unresolved_questions == []


def test_apply_delta_sets_summary_and_position():
    merged = apply_delta(
        InterviewState(session_id="s"),
        StateDelta(candidate_position="reconcile before retrying"),
        answer_summary="Treated it as unknown outcome.",
    )
    assert merged.previous_candidate_position == "reconcile before retrying"
    assert merged.previous_answer_summary == "Treated it as unknown outcome."


def test_apply_delta_only_overwrites_scalars_when_present():
    state = InterviewState(session_id="s", current_topic="webhooks")
    assert apply_delta(state, StateDelta()).current_topic == "webhooks"
    assert apply_delta(state, StateDelta(current_topic="oauth")).current_topic == "oauth"


def test_state_lists_are_bounded():
    state = InterviewState(session_id="s")
    state = apply_delta(state, StateDelta(new_constraints=[f"c{i}" for i in range(80)]))
    assert len(state.interviewer_constraints) == 40
    assert state.interviewer_constraints[-1] == "c79"


def test_render_state_omits_empty_sections():
    rendered = render_state_for_prompt(
        InterviewState(session_id="s", turn_number=2, interviewer_constraints=["no idempotency"])
    )
    assert "no idempotency" in rendered
    assert "accepted_tradeoffs" not in rendered


def test_render_state_marks_the_first_turn():
    assert "first question" in render_state_for_prompt(InterviewState(session_id="s"))
