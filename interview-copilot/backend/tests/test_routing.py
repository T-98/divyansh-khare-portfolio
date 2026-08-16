"""Router: chip shortcuts, invariant clamping, keyword fallback."""

from __future__ import annotations

import pytest

from app.agents.router import (
    chip_intent,
    deterministic_route,
    fallback_decision,
    normalise_chip,
    sanitise,
)
from app.models.interview import InterviewState
from tests.conftest import make_routing


def state(turn: int = 1, **kwargs) -> InterviewState:
    return InterviewState(session_id="s", turn_number=turn, **kwargs)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("deeper", "deeper"),
        ("  Deeper  ", "deeper"),
        ("PUSH!", "push"),
        ("why?", "why"),
        ("what if it times out", None),
        ("deeper into the retry logic", None),
    ],
)
def test_chip_detection(text, expected):
    assert normalise_chip(text) == expected


def test_chip_carries_previous_domains_forward():
    decision = deterministic_route("deeper", state(), previous_domains=["agents"])
    assert decision is not None
    assert decision.domains == ["agents"]
    assert decision.is_followup is True


def test_chip_defaults_when_no_previous_domain():
    decision = deterministic_route("deeper", state(), previous_domains=[])
    assert decision is not None and decision.domains == ["integration"]


def test_debug_chip_forces_reliability():
    decision = deterministic_route("debug", state(), previous_domains=["agents"])
    assert decision is not None and decision.domains == ["reliability"]


def test_screen_chip_asks_for_two_specialists():
    decision = deterministic_route("screen", state(turn=0))
    assert decision is not None
    assert decision.needs_second_specialist is True
    assert decision.domains == ["integration", "customer_implementation"]
    assert decision.response_budget == "walkthrough"


def test_followup_chip_on_turn_zero_defers_to_the_model():
    assert deterministic_route("deeper", state(turn=0)) is None
    assert deterministic_route("why", state(turn=0)) is None


def test_non_chip_text_is_not_routed_deterministically():
    assert deterministic_route("how does OAuth refresh work", state()) is None


def test_chip_intent_expands_to_a_question():
    assert chip_intent("push") == "the interviewer is pushing back on that answer"
    assert chip_intent("not a chip") is None


def test_sanitise_caps_domains_at_two():
    cleaned = sanitise(
        make_routing(domains=["integration", "agents", "reliability", "customer_implementation"])
    )
    assert len(cleaned.domains) == 2


def test_sanitise_drops_unknown_and_duplicate_domains():
    decision = make_routing()
    decision.domains = ["integration", "integration"]  # type: ignore[assignment]
    assert sanitise(decision).domains == ["integration"]


def test_sanitise_defaults_empty_domains():
    assert sanitise(make_routing(domains=[])).domains == ["integration"]


def test_sanitise_clears_second_specialist_when_only_one_domain():
    cleaned = sanitise(make_routing(domains=["agents"], needs_second_specialist=True))
    assert cleaned.needs_second_specialist is False


def test_sanitise_keeps_incidents_tactical():
    cleaned = sanitise(
        make_routing(mode="incident", domains=["integration", "reliability"], response_budget="walkthrough")
    )
    assert cleaned.response_budget == "medium"
    assert cleaned.domains[0] == "reliability"


def test_sanitise_trims_blank_subquestions_and_probe():
    cleaned = sanitise(make_routing(explicit_subquestions=["  ", "real one"], likely_next_probe="  "))
    assert cleaned.explicit_subquestions == ["real one"]
    assert cleaned.likely_next_probe is None


@pytest.mark.parametrize(
    "text,mode,domain",
    [
        ("users cannot authenticate in production right now", "incident", "reliability"),
        ("the agent called the wrong tool", "agent_systems", "agents"),
        ("we keep getting 429 responses", "scenario", "reliability"),
        ("the customer has no api at all", "customer_requirements", "customer_implementation"),
        ("how do you map their schema to ours", "scenario", "integration"),
    ],
)
def test_keyword_fallback_is_sane(text, mode, domain):
    decision = fallback_decision(text, state(turn=0))
    assert decision.mode == mode
    assert decision.domains == [domain]


def test_keyword_fallback_marks_short_later_turns_as_followups():
    assert fallback_decision("why though", state(turn=4)).is_followup is True
