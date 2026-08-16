"""Prompt loading, slicing, and the strict-schema translation."""

from __future__ import annotations

import pytest

from app.agents.editor import build_payload, parse_specialist_notes, synthesize_from_specialist
from app.agents.llm import schema_for, strictify
from app.agents.prompt_loader import (
    SPECIALIST_SECTION,
    editor_prompt,
    parse_sections,
    router_prompt,
    specialist_prompt,
)
from app.models.interview import InterviewResponse, InterviewState
from app.models.routing import RoutingDecision
from tests.conftest import make_routing


def test_all_expected_sections_parse():
    sections = parse_sections()
    assert set(range(1, 16)).issubset(sections.keys())


def test_specialist_prompt_contains_only_its_own_specialist_section():
    prompt = specialist_prompt("integration")
    assert "# 6. Integration Specialist" in prompt
    assert "# 7. AI Agent Specialist" not in prompt
    assert "You are the integration specialist" in prompt


@pytest.mark.parametrize("domain", sorted(SPECIALIST_SECTION))
def test_every_specialist_composes(domain):
    prompt = specialist_prompt(domain)
    assert "# 1. Shared mission" in prompt
    assert f"You are the {domain} specialist" in prompt
    assert len(prompt) > 2000


def test_unknown_specialist_is_rejected():
    with pytest.raises(ValueError):
        specialist_prompt("marketing")


def test_router_prompt_includes_mode_definitions_but_no_specialist_bodies():
    prompt = router_prompt()
    assert "# 10. Interview mode detection" in prompt
    assert "You never answer the interviewer" in prompt
    assert "# 6. Integration Specialist" not in prompt


def test_editor_prompt_includes_checklist_and_anti_repetition():
    prompt = editor_prompt()
    assert "# 15." in prompt
    assert "# 4. Anti-repetition" in prompt
    assert "# 11. Follow-up continuity" in prompt


def test_specialist_prompts_are_smaller_than_the_whole_document():
    from app.agents.prompt_loader import SPECIALIST_DOC, read_prompt_file

    whole = len(read_prompt_file(SPECIALIST_DOC))
    assert len(specialist_prompt("agents")) < whole, "slicing should cut prompt size"


# --- strict schema ---------------------------------------------------------


def _assert_strict(node, path="root"):
    if isinstance(node, dict):
        assert "default" not in node and "title" not in node, path
        if "properties" in node:
            assert node.get("additionalProperties") is False, path
            assert set(node["required"]) == set(node["properties"]), path
        for key, value in node.items():
            _assert_strict(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _assert_strict(value, f"{path}[{index}]")


@pytest.mark.parametrize("model", [InterviewResponse, RoutingDecision])
def test_schema_is_strict_mode_compatible(model):
    _assert_strict(schema_for(model, "x")["json_schema"]["schema"])


def test_say_is_the_first_streamed_field():
    schema = schema_for(InterviewResponse, "x")["json_schema"]["schema"]
    assert list(schema["properties"])[0] == "say"


def test_strictify_handles_nested_and_optional_fields():
    cleaned = strictify(
        {
            "properties": {"a": {"type": "string", "default": "x", "title": "A"}},
            "type": "object",
        }
    )
    assert cleaned["required"] == ["a"]
    assert "default" not in cleaned["properties"]["a"]


# --- editor payload and fallbacks -----------------------------------------


def test_editor_payload_carries_state_and_subquestions():
    payload = build_payload(
        "what if it times out",
        make_routing(explicit_subquestions=["do you retry", "how do you know"]),
        InterviewState(session_id="s", turn_number=2, interviewer_constraints=["no idempotency"]),
        {"integration": "ANSWER: unknown outcome"},
    )
    assert "do you retry" in payload
    assert "no idempotency" in payload
    assert "--- integration ---" in payload


def test_editor_payload_flags_a_changed_assumption():
    payload = build_payload(
        "assume no idempotency",
        make_routing(changes_prior_assumption=True),
        InterviewState(session_id="s"),
        {},
    )
    assert "no longer holds" in payload
    assert "invalidated_advice" in payload


def test_editor_payload_handles_missing_specialist_notes():
    payload = build_payload("anything", make_routing(), InterviewState(session_id="s"), {})
    assert "none available this turn" in payload


def test_specialist_notes_parse_into_sections():
    parsed = parse_specialist_notes(
        "ANSWER: Treat it as unknown.\n"
        "REASONING: - check idempotency\n- reconcile\n"
        "MECHANICS: 1. look up by reference\n"
        "DEEPER: write intent first"
    )
    assert parsed["ANSWER"] == ["Treat it as unknown."]
    assert parsed["REASONING"] == ["check idempotency", "reconcile"]
    assert parsed["MECHANICS"] == ["look up by reference"]


def test_synthesis_builds_a_usable_answer_without_a_model():
    response = synthesize_from_specialist(
        {"integration": "ANSWER: Treat it as unknown.\nREASONING: reconcile\nMECHANICS: check ids"},
        make_routing(),
    )
    assert response is not None
    assert response.say == "Treat it as unknown."
    assert response.path == ["reconcile"]


def test_synthesis_returns_none_without_specialist_output():
    assert synthesize_from_specialist({}, make_routing()) is None


def test_synthesis_degrades_when_labels_are_missing():
    response = synthesize_from_specialist({"integration": "just some raw prose here"}, make_routing())
    assert response is not None and response.say.startswith("just some raw prose")
