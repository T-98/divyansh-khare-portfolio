"""Shared fixtures. Every test here runs offline — OpenAI is always mocked."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents import editor as editor_agent
from app.agents import router as router_agent
from app.agents import specialists as specialist_agent
from app.agents.llm import CallMeta
from app.agents.prompt_loader import clear_cache
from app.config import get_settings
from app.models.interview import InterviewResponse, StateDelta
from app.models.routing import RoutingDecision


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DEBUG_AGENT_OUTPUT", "true")
    monkeypatch.setenv("ROUTER_MODEL", "router-test")
    monkeypatch.setenv("SPECIALIST_MODEL", "specialist-test")
    monkeypatch.setenv("EDITOR_MODEL", "editor-test")
    monkeypatch.setenv("DEEP_MODEL", "deep-test")
    get_settings.cache_clear()
    clear_cache()
    yield
    get_settings.cache_clear()


def make_routing(**overrides: Any) -> RoutingDecision:
    base: dict[str, Any] = {
        "mode": "scenario",
        "domains": ["integration"],
        "complexity": "medium",
        "is_followup": False,
        "changes_prior_assumption": False,
        "explicit_subquestions": ["what do you do"],
        "interviewer_is_testing": "failure semantics",
        "response_budget": "medium",
        "needs_second_specialist": False,
        "likely_next_probe": "what if it happens again",
    }
    base.update(overrides)
    return RoutingDecision(**base)


def make_response(**overrides: Any) -> InterviewResponse:
    base: dict[str, Any] = {
        "say": "I'd treat that as an unknown outcome rather than a failure.",
        "path": ["timeout", "reconcile", "safe retry"],
        "build": [
            "Check whether the provider exposes an idempotency key.",
            "Look up the operation by an external reference before writing again.",
        ],
        "push": "Reconciliation needs a durable record written before the call.",
        "next_probe": "what if reconciliation is also unavailable",
        "response_mode": "scenario",
        "answer_summary": "Treated the timeout as unknown outcome; reconcile before retry.",
        "state_delta": StateDelta(new_constraints=["booking POST timed out"]),
    }
    base.update(overrides)
    return InterviewResponse(**base)


class FakeAgents:
    """Installs deterministic stand-ins for all three model stages."""

    def __init__(self) -> None:
        self.routing = make_routing()
        self.response = make_response()
        self.specialist_text = (
            "ANSWER: Treat it as an unknown outcome.\n"
            "REASONING: check idempotency\nreconcile\nretry only if safe\n"
            "MECHANICS: Look for an external reference id.\nDo not repeat a consequential write.\n"
            "DEEPER: Write an intent record before the call.\n"
            "RISKS: Do not claim the provider supports idempotency."
        )
        self.router_calls = 0
        self.specialist_calls: list[str] = []
        self.editor_calls = 0
        self.specialist_delay = 0.0
        self.specialist_error: Exception | None = None
        self.editor_error: Exception | None = None
        self.emergency_error: Exception | None = None
        self.concurrency = 0
        self.max_concurrency = 0

    def install(self, monkeypatch) -> "FakeAgents":
        async def fake_route(text, state):
            self.router_calls += 1
            return router_agent.sanitise(self.routing), CallMeta(model="router-test", latency_ms=5)

        async def fake_text_call(*, model, system, user, timeout, max_tokens=None):
            self.concurrency += 1
            self.max_concurrency = max(self.max_concurrency, self.concurrency)
            try:
                # `system` carries the specialist overlay; record which one ran.
                for domain in ("integration", "agents", "reliability", "customer_implementation"):
                    if f"You are the {domain} specialist" in system:
                        self.specialist_calls.append(domain)
                        break
                if self.specialist_delay:
                    await asyncio.sleep(self.specialist_delay)
                if self.specialist_error:
                    raise self.specialist_error
                return self.specialist_text, CallMeta(model=model, latency_ms=10)
            finally:
                self.concurrency -= 1

        async def fake_edit(text, decision, state, outputs):
            self.editor_calls += 1
            if self.editor_error:
                raise self.editor_error
            return self.response.model_copy(deep=True), CallMeta(model="editor-test", latency_ms=20)

        async def fake_emergency(text, decision, state, outputs):
            if self.emergency_error:
                raise self.emergency_error
            meta = CallMeta(model="specialist-test", latency_ms=15, fallback_used=True)
            return self.response.model_copy(deep=True), meta

        monkeypatch.setattr(router_agent, "route", fake_route)
        monkeypatch.setattr(specialist_agent, "text_call", fake_text_call)
        monkeypatch.setattr(editor_agent, "edit", fake_edit)
        monkeypatch.setattr(editor_agent, "emergency_answer", fake_emergency)
        return self


@pytest.fixture
def fake_agents(monkeypatch) -> FakeAgents:
    return FakeAgents().install(monkeypatch)


@pytest.fixture
def client(env):
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def session_id(client) -> str:
    return client.post("/api/sessions").json()["session_id"]
