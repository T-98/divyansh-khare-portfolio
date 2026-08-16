"""Real-model smoke tests. Skipped unless explicitly enabled.

    LIVE_TESTS=1 OPENAI_API_KEY=sk-... .venv/bin/python -m pytest -m live

These exist to confirm the configured model IDs actually work on this account
before the interview, and that structured output parses. Everything else in the
suite runs offline.
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("LIVE_TESTS") != "1",
        reason="set LIVE_TESTS=1 to hit the real API",
    ),
]


@pytest.fixture
def live_env(monkeypatch, tmp_path):
    """Use the real .env values, not the fake ones from conftest."""
    from app.config import get_settings

    for var in ("ROUTER_MODEL", "SPECIALIST_MODEL", "EDITOR_MODEL", "DEEP_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/live.db")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


async def _run(settings, prompt: str):
    from app.persistence.sqlite import SQLiteSessionStore
    from app.services.orchestrator import Orchestrator

    store = SQLiteSessionStore(":memory:")
    await store.init()
    orchestrator = Orchestrator(store)
    session = await orchestrator.create_session()
    try:
        return await orchestrator.handle_message(session.session_id, prompt)
    finally:
        await store.close()


async def test_configured_models_answer_a_real_question(live_env):
    response = await _run(live_env, "A booking POST to the provider timed out. Do you retry?")

    assert response.say.strip(), "editor returned an empty opening"
    assert response.path, "no reasoning path"
    assert response.mode
    assert response.debug is not None
    assert not response.debug.fallback_used, (
        f"a configured model was rejected: {response.debug.fallback_used}"
    )
    print(f"\nmode={response.mode} latency={response.latency_ms}ms\nSAY: {response.say}")


async def test_live_followup_keeps_the_scenario(live_env):
    from app.persistence.sqlite import SQLiteSessionStore
    from app.services.orchestrator import Orchestrator

    store = SQLiteSessionStore(":memory:")
    await store.init()
    orchestrator = Orchestrator(store)
    session = await orchestrator.create_session()
    try:
        await orchestrator.handle_message(session.session_id, "A booking POST timed out.")
        second = await orchestrator.handle_message(
            session.session_id, "Assume the provider has no idempotency support."
        )
    finally:
        await store.close()

    assert second.turn == 2
    assert second.debug is not None
    state = second.debug.state
    assert state["interviewer_constraints"], "no constraints carried into state"
