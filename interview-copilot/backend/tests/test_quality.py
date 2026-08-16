"""Anti-repetition gate, budgets, and coverage heuristics."""

from __future__ import annotations

from app.models.interview import InterviewResponse
from app.services.partial_json import partial_string_field
from app.services.quality import (
    budget_notes,
    coverage_notes,
    dedupe_response,
    run_quality_gate,
    similarity,
)


def response(**kwargs) -> InterviewResponse:
    base = {
        "say": "I'd treat that as an unknown outcome, not a failure.",
        "path": ["timeout", "reconcile", "safe retry"],
        "build": ["Check whether the provider exposes an idempotency key."],
        "push": None,
        "next_probe": None,
        "response_mode": "scenario",
        "answer_summary": "summary",
    }
    base.update(kwargs)
    return InterviewResponse(**base)


def test_similarity_catches_a_restatement():
    assert similarity(
        "I'd treat that as an unknown outcome, not a failure.",
        "Treat it as an unknown outcome rather than a failure.",
    ) >= 0.7


def test_similarity_ignores_unrelated_text():
    assert similarity("verify the webhook signature", "increase the connection pool") < 0.3


def test_build_bullet_restating_say_is_dropped():
    cleaned, notes = dedupe_response(
        response(build=["Treat it as an unknown outcome rather than a failure.", "Check idempotency support."])
    )
    assert cleaned.build == ["Check idempotency support."]
    assert any("already stated in SAY" in note for note in notes)


def test_duplicate_build_bullets_are_collapsed():
    cleaned, notes = dedupe_response(
        response(build=["Verify the webhook signature first.", "First, verify the webhook signature."])
    )
    assert len(cleaned.build) == 1
    assert any("duplicate BUILD" in note for note in notes)


def test_duplicate_path_steps_are_collapsed():
    cleaned, _ = dedupe_response(response(path=["reconcile", "reconcile", "safe retry"]))
    assert cleaned.path == ["reconcile", "safe retry"]


def test_push_that_only_restates_is_removed():
    cleaned, notes = dedupe_response(
        response(push="I would treat that as an unknown outcome, not a failure.")
    )
    assert cleaned.push is None
    assert any("IF THEY PUSH" in note for note in notes)


def test_push_with_genuinely_new_material_survives():
    cleaned, _ = dedupe_response(
        response(push="Write a durable intent record before the call so reconciliation has an anchor.")
    )
    assert cleaned.push is not None


def test_next_probe_restating_the_answer_is_removed():
    cleaned, _ = dedupe_response(
        response(next_probe="Treat it as an unknown outcome, not a failure.")
    )
    assert cleaned.next_probe is None


def test_build_bullets_may_expand_a_path_step():
    # PATH is direction only, so a BUILD bullet that fleshes it out is not repetition.
    cleaned, _ = dedupe_response(
        response(path=["reconcile"], build=["Reconcile against the provider before writing again."])
    )
    assert cleaned.build


def test_empty_and_whitespace_entries_are_stripped():
    cleaned, _ = dedupe_response(response(path=["  ", "reconcile"], build=["", "  "]))
    assert cleaned.path == ["reconcile"]
    assert cleaned.build == []


def test_budget_notes_flag_a_bloated_short_answer():
    long_answer = response(say=" ".join(["word"] * 400))
    assert budget_notes(long_answer, "short")


def test_budget_notes_stay_quiet_inside_range():
    normal = response(say=" ".join(["word"] * 150))
    assert budget_notes(normal, "medium") == []


def test_coverage_notes_flag_an_unanswered_subquestion():
    notes = coverage_notes(response(), ["how would you handle refresh token revocation"])
    assert notes and "uncovered" in notes[0]


def test_coverage_notes_are_quiet_when_covered():
    covered = response(build=["Check whether the provider exposes an idempotency key on retry."])
    assert coverage_notes(covered, ["idempotency key on retry"]) == []


def test_quality_gate_returns_cleaned_response_and_notes():
    cleaned, notes = run_quality_gate(
        response(build=["Treat it as an unknown outcome rather than a failure."]),
        budget="medium",
        subquestions=["what do you do"],
    )
    assert cleaned.build == []
    assert notes


# --- partial JSON streaming ------------------------------------------------


def test_partial_string_field_reads_an_incomplete_value():
    value, complete = partial_string_field('{"say": "I would treat that as', "say")
    assert value == "I would treat that as"
    assert complete is False


def test_partial_string_field_detects_completion():
    value, complete = partial_string_field('{"say": "done.", "path": [', "say")
    assert (value, complete) == ("done.", True)


def test_partial_string_field_handles_escapes():
    value, _ = partial_string_field('{"say": "they said \\"retry\\" first', "say")
    assert value == 'they said "retry" first'


def test_partial_string_field_handles_a_split_escape():
    value, complete = partial_string_field('{"say": "quote \\', "say")
    assert value == "quote " and complete is False


def test_partial_string_field_missing_key():
    assert partial_string_field('{"path": []}', "say") == ("", False)


def test_partial_string_field_null_value_is_complete_and_empty():
    assert partial_string_field('{"push": null}', "push") == ("", True)


def test_partial_string_field_handles_unicode_escape():
    value, _ = partial_string_field('{"say": "caf\\u00e9 rate limit', "say")
    assert value == "café rate limit"
