"""Health, session lifecycle, and message persistence."""

from __future__ import annotations


def test_health_reports_configured_models(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["openai_key_configured"] is True
    assert body["models"]["router"] == "router-test"
    assert "editor" in body["models"]


def test_create_session_returns_id_and_timestamp(client):
    response = client.post("/api/sessions")
    assert response.status_code == 201
    body = response.json()
    assert body["session_id"]
    assert body["created_at"]


def test_get_unknown_session_is_404(client):
    assert client.get("/api/sessions/does-not-exist").status_code == 404


def test_delete_session_removes_it(client, session_id):
    assert client.delete(f"/api/sessions/{session_id}").status_code == 204
    assert client.get(f"/api/sessions/{session_id}").status_code == 404
    assert client.delete(f"/api/sessions/{session_id}").status_code == 404


def test_message_is_persisted_and_replayable(client, session_id, fake_agents):
    posted = client.post(
        f"/api/sessions/{session_id}/messages",
        json={"text": "the booking POST timed out, what do you do"},
    )
    assert posted.status_code == 200
    body = posted.json()
    assert body["turn"] == 1
    assert body["say"]
    assert body["mode"] == "scenario"
    assert body["latency_ms"] >= 0

    detail = client.get(f"/api/sessions/{session_id}").json()
    assert detail["turn_count"] == 1
    assert detail["turns"][0]["interviewer_text"].startswith("the booking POST")
    assert detail["turns"][0]["say"] == body["say"]
    assert detail["state"]["turn_number"] == 1


def test_turn_numbers_increment(client, session_id, fake_agents):
    for expected in (1, 2, 3):
        body = client.post(
            f"/api/sessions/{session_id}/messages", json={"text": f"question {expected}"}
        ).json()
        assert body["turn"] == expected


def test_message_to_unknown_session_is_404(client, fake_agents):
    response = client.post("/api/sessions/nope/messages", json={"text": "hello"})
    assert response.status_code == 404


def test_blank_message_is_rejected(client, session_id, fake_agents):
    assert client.post(f"/api/sessions/{session_id}/messages", json={"text": "   "}).status_code == 422
    assert client.post(f"/api/sessions/{session_id}/messages", json={"text": ""}).status_code == 422


def test_empty_optional_fields_serialise_as_null(client, session_id, fake_agents):
    fake_agents.response = fake_agents.response.model_copy(
        update={"push": None, "next_probe": None}
    )
    body = client.post(f"/api/sessions/{session_id}/messages", json={"text": "define idempotency"}).json()
    assert body["push"] is None
    assert body["next_probe"] is None
    assert body["path"] and isinstance(body["path"], list)
