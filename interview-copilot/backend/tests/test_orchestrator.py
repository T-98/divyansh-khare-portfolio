"""Specialist selection, concurrency, continuity, and graceful failure."""

from __future__ import annotations

import json
import time

import pytest

from app.agents.llm import LLMError
from app.models.interview import StateDelta
from tests.conftest import make_routing


def post(client, session_id, text):
    return client.post(f"/api/sessions/{session_id}/messages", json={"text": text})


def test_one_specialist_is_the_default(client, session_id, fake_agents):
    body = post(client, session_id, "how do webhooks get deduplicated").json()
    assert fake_agents.specialist_calls == ["integration"]
    assert body["debug"]["specialists"] == ["integration"]


def test_second_specialist_only_when_router_asks(client, session_id, fake_agents):
    fake_agents.routing = make_routing(
        domains=["integration", "customer_implementation"],
        needs_second_specialist=True,
        mode="screen_share",
        response_budget="walkthrough",
    )
    post(client, session_id, "walk me through wiring their booking API")
    assert sorted(fake_agents.specialist_calls) == ["customer_implementation", "integration"]


def test_two_domains_without_the_flag_still_runs_one(client, session_id, fake_agents):
    fake_agents.routing = make_routing(
        domains=["integration", "reliability"], needs_second_specialist=False
    )
    post(client, session_id, "why did that fail")
    assert fake_agents.specialist_calls == ["integration"]


def test_never_more_than_two_specialists(client, session_id, fake_agents):
    fake_agents.routing = make_routing(
        domains=["integration", "reliability", "agents", "customer_implementation"],
        needs_second_specialist=True,
    )
    post(client, session_id, "everything at once")
    assert len(fake_agents.specialist_calls) == 2


def test_specialists_run_concurrently(client, session_id, fake_agents):
    fake_agents.routing = make_routing(
        domains=["integration", "reliability"], needs_second_specialist=True
    )
    fake_agents.specialist_delay = 0.25

    started = time.perf_counter()
    post(client, session_id, "mixed question")
    elapsed = time.perf_counter() - started

    assert fake_agents.max_concurrency == 2
    assert elapsed < 0.45, "two specialists ran sequentially"


def test_incident_forces_reliability_primary_and_medium_budget(client, session_id, fake_agents):
    fake_agents.routing = make_routing(
        mode="incident",
        domains=["integration", "reliability"],
        needs_second_specialist=True,
        response_budget="walkthrough",
    )
    body = post(client, session_id, "users cannot authenticate, 5 minutes to unblock").json()
    assert body["debug"]["routing"]["domains"][0] == "reliability"
    assert body["debug"]["routing"]["response_budget"] == "medium"


def test_state_accumulates_across_turns(client, session_id, fake_agents):
    fake_agents.response = fake_agents.response.model_copy(
        update={"state_delta": StateDelta(new_constraints=["booking POST timed out"])}
    )
    post(client, session_id, "the booking POST timed out")

    fake_agents.response = fake_agents.response.model_copy(
        update={"state_delta": StateDelta(new_constraints=["provider has no idempotency support"])}
    )
    post(client, session_id, "assume the provider has no idempotency")

    fake_agents.response = fake_agents.response.model_copy(
        update={
            "state_delta": StateDelta(
                new_constraints=["provider cannot be queried afterwards"],
                invalidated_advice="reconciliation by lookup no longer works",
            )
        }
    )
    body = post(client, session_id, "you also cannot query the provider afterwards").json()

    constraints = body["debug"]["state"]["interviewer_constraints"]
    assert constraints == [
        "booking POST timed out",
        "provider has no idempotency support",
        "provider cannot be queried afterwards",
    ]
    assert body["debug"]["state_delta"]["invalidated_advice"]
    assert body["debug"]["state"]["turn_number"] == 3


def test_state_is_not_duplicated_when_a_constraint_repeats(client, session_id, fake_agents):
    fake_agents.response = fake_agents.response.model_copy(
        update={"state_delta": StateDelta(new_constraints=["Provider has no idempotency"])}
    )
    post(client, session_id, "first")
    body = post(client, session_id, "second").json()
    assert body["debug"]["state"]["interviewer_constraints"] == ["Provider has no idempotency"]


def test_previous_answer_summary_carries_forward(client, session_id, fake_agents):
    post(client, session_id, "first question")
    detail = client.get(f"/api/sessions/{session_id}").json()
    assert detail["state"]["previous_answer_summary"].startswith("Treated the timeout")


def test_chip_skips_the_router(client, session_id, fake_agents):
    post(client, session_id, "the booking POST timed out")
    calls_before = fake_agents.router_calls

    body = post(client, session_id, "deeper").json()
    assert fake_agents.router_calls == calls_before, "chip should not call the router"
    assert body["debug"]["router_skipped"] is True
    assert body["debug"]["timings"]["router_latency_ms"] == 0


def test_chip_on_first_turn_still_routes(client, session_id, fake_agents):
    post(client, session_id, "deeper")
    assert fake_agents.router_calls == 1


def test_screen_chip_runs_two_specialists(client, session_id, fake_agents):
    post(client, session_id, "screen")
    assert sorted(fake_agents.specialist_calls) == ["customer_implementation", "integration"]


def test_editor_failure_falls_back_to_direct_call(client, session_id, fake_agents):
    fake_agents.editor_error = LLMError("editor exploded")
    body = post(client, session_id, "what now").json()
    assert body["say"]
    assert any("editor" in note for note in body["debug"]["fallback_used"])


def test_both_editors_failing_synthesises_from_specialist_notes(client, session_id, fake_agents):
    fake_agents.editor_error = LLMError("editor exploded")
    fake_agents.emergency_error = LLMError("fallback exploded too")
    body = post(client, session_id, "what now").json()
    assert body["say"] == "Treat it as an unknown outcome."
    assert body["path"] == ["check idempotency", "reconcile", "retry only if safe"]
    assert any("specialist notes" in note for note in body["debug"]["fallback_used"])


def test_specialist_failure_still_produces_an_answer(client, session_id, fake_agents):
    fake_agents.specialist_error = LLMError("specialist down")
    body = post(client, session_id, "what now").json()
    assert body["say"]
    assert any("specialist down" in note for note in body["debug"]["fallback_used"])


def test_everything_failing_returns_503(client, session_id, fake_agents):
    fake_agents.specialist_error = LLMError("specialist down")
    fake_agents.editor_error = LLMError("editor down")
    fake_agents.emergency_error = LLMError("fallback down")
    assert post(client, session_id, "what now").status_code == 503


def test_persistence_failure_is_surfaced_not_hidden(client, session_id, fake_agents, monkeypatch):
    async def broken_append(_turn):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(client.app.state.store, "append_turn", broken_append)
    body = post(client, session_id, "what now").json()

    assert body["say"], "the answer must still be delivered"
    assert body["warning"] and "not saved" in body["warning"].lower()
    assert body["debug"]["persistence_ok"] is False


def test_debug_drawer_payload_is_complete(client, session_id, fake_agents):
    debug = post(client, session_id, "what happens on a duplicate webhook").json()["debug"]
    for key in (
        "mode",
        "domains",
        "specialists",
        "router_model",
        "specialist_model",
        "editor_model",
        "timings",
        "routing",
        "state",
        "state_delta",
        "specialist_output",
        "fallback_used",
        "quality_notes",
    ):
        assert key in debug, key
    assert debug["timings"]["total_latency_ms"] >= 0
    assert debug["specialist_output"]["integration"], "DEBUG_AGENT_OUTPUT=true should include notes"


def test_deep_complexity_uses_the_deep_model(client, session_id, fake_agents):
    fake_agents.routing = make_routing(complexity="deep")
    body = post(client, session_id, "hard distributed systems question").json()
    assert body["debug"]["specialist_model"] == "deep-test"


def test_deep_model_is_not_used_for_two_specialists(client, session_id, fake_agents):
    fake_agents.routing = make_routing(
        complexity="deep", domains=["integration", "agents"], needs_second_specialist=True
    )
    body = post(client, session_id, "hard mixed question").json()
    assert body["debug"]["specialist_model"] == "specialist-test"


def test_stream_endpoint_emits_say_before_final(client, session_id, fake_agents, monkeypatch):
    from app.agents import editor as editor_agent
    from app.agents.llm import CallMeta

    full_say = fake_agents.response.say

    async def fake_stream(text, decision, state, outputs):
        yield "say", full_say[:14]
        yield "say", full_say
        yield "final", (fake_agents.response.model_copy(deep=True), CallMeta(model="editor-test"))

    monkeypatch.setattr(editor_agent, "edit_stream", fake_stream)

    with client.stream(
        "POST", f"/api/sessions/{session_id}/messages/stream", json={"text": "what now"}
    ) as response:
        assert response.status_code == 200
        events = [
            json.loads(line[len("data: ") :])
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]

    kinds = [event["type"] for event in events]
    assert kinds.index("say") < kinds.index("final")
    assert kinds[0] == "routing"
    assert events[-1]["type"] == "final"
    assert events[-1]["payload"]["say"] == full_say
    # The partial arrives before the object is finished — that is the whole point.
    assert events[kinds.index("say")]["text"] == full_say[:14]

    # The streamed turn must persist exactly like the blocking one.
    assert client.get(f"/api/sessions/{session_id}").json()["turn_count"] == 1


def test_stream_unknown_session_is_404(client, fake_agents):
    response = client.post("/api/sessions/nope/messages/stream", json={"text": "hi"})
    assert response.status_code == 404


@pytest.mark.parametrize("chip", ["deeper", "why", "debug", "scale", "push", "technical"])
def test_all_chips_route_deterministically_after_turn_one(client, session_id, fake_agents, chip):
    post(client, session_id, "opening scenario")
    before = fake_agents.router_calls
    body = post(client, session_id, chip).json()
    assert fake_agents.router_calls == before
    assert body["debug"]["router_skipped"] is True
