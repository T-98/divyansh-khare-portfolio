"""Transcription endpoint: cleanup, validation, failure handling."""

from __future__ import annotations

import glob
import tempfile

import pytest

from app.services.transcription import (
    OpenAITranscriber,
    TranscriptionError,
    TranscriptionResult,
    Transcriber,
    extension_for,
    set_transcriber,
)


class StubTranscriber(Transcriber):
    def __init__(self, text="the booking POST timed out", error: Exception | None = None):
        self.text = text
        self.error = error
        self.received: bytes | None = None
        self.content_type: str | None = None

    async def transcribe(self, audio, *, content_type=None, filename=None):
        self.received = audio
        self.content_type = content_type
        if self.error:
            raise self.error
        return TranscriptionResult(text=self.text, latency_ms=120, model="stub-model")


@pytest.fixture
def stub():
    transcriber = StubTranscriber()
    set_transcriber(transcriber)
    yield transcriber
    set_transcriber(None)


def test_transcription_returns_text(client, stub):
    response = client.post(
        "/api/transcribe",
        files={"audio": ("clip.webm", b"\x1a\x45\xdf\xa3" + b"0" * 2048, "audio/webm")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "the booking POST timed out"
    assert body["model"] == "stub-model"
    assert body["latency_ms"] == 120
    assert stub.content_type == "audio/webm"


def test_empty_upload_is_rejected(client, stub):
    response = client.post("/api/transcribe", files={"audio": ("clip.webm", b"", "audio/webm")})
    assert response.status_code == 422


def test_missing_file_is_rejected(client, stub):
    assert client.post("/api/transcribe").status_code == 422


def test_transcription_failure_returns_422_with_a_message(client):
    set_transcriber(StubTranscriber(error=TranscriptionError("recording too short")))
    try:
        response = client.post(
            "/api/transcribe", files={"audio": ("c.webm", b"0" * 1024, "audio/webm")}
        )
        assert response.status_code == 422
        assert "recording too short" in response.json()["detail"]
    finally:
        set_transcriber(None)


def test_unexpected_error_returns_502(client):
    set_transcriber(StubTranscriber(error=RuntimeError("network gone")))
    try:
        response = client.post(
            "/api/transcribe", files={"audio": ("c.webm", b"0" * 1024, "audio/webm")}
        )
        assert response.status_code == 502
    finally:
        set_transcriber(None)


def test_oversized_upload_is_rejected(client, stub, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_transcribe_bytes", 1024)
    response = client.post(
        "/api/transcribe", files={"audio": ("c.webm", b"0" * 4096, "audio/webm")}
    )
    assert response.status_code == 413


@pytest.mark.parametrize(
    "content_type,filename,expected",
    [
        ("audio/webm", "clip.webm", ".webm"),
        ("audio/mp4", "clip.mp4", ".mp4"),
        ("audio/ogg;codecs=opus", None, ".ogg"),
        ("application/octet-stream", None, ".webm"),
        (None, "recording.wav", ".wav"),
    ],
)
def test_extension_selection(content_type, filename, expected):
    assert extension_for(content_type, filename) == expected


@pytest.mark.asyncio
async def test_short_audio_is_rejected_before_any_upload():
    with pytest.raises(TranscriptionError, match="too short"):
        await OpenAITranscriber().transcribe(b"tiny", content_type="audio/webm")


@pytest.mark.asyncio
async def test_temp_audio_is_deleted_even_when_the_call_fails(monkeypatch):
    """Raw audio must never outlive the request, including on failure."""
    from app.agents import llm

    async def fake_client():
        return object()

    async def exploding_call(client, path, model, timeout):
        assert glob.glob(f"{tempfile.gettempdir()}/interview-audio-*"), "temp file should exist mid-call"
        raise RuntimeError("upstream is down")

    monkeypatch.setattr(llm, "get_client", fake_client)
    monkeypatch.setattr(OpenAITranscriber, "_call", staticmethod(exploding_call))

    before = set(glob.glob(f"{tempfile.gettempdir()}/interview-audio-*"))
    with pytest.raises(TranscriptionError):
        await OpenAITranscriber().transcribe(b"0" * 4096, content_type="audio/webm")
    after = set(glob.glob(f"{tempfile.gettempdir()}/interview-audio-*"))

    assert after == before, "temp audio file was left on disk"


@pytest.mark.asyncio
async def test_temp_audio_is_deleted_on_success(monkeypatch):
    from app.agents import llm

    async def fake_client():
        return object()

    async def ok_call(client, path, model, timeout):
        return "transcribed text"

    monkeypatch.setattr(llm, "get_client", fake_client)
    monkeypatch.setattr(OpenAITranscriber, "_call", staticmethod(ok_call))

    before = set(glob.glob(f"{tempfile.gettempdir()}/interview-audio-*"))
    result = await OpenAITranscriber().transcribe(b"0" * 4096, content_type="audio/webm")
    assert result.text == "transcribed text"
    assert set(glob.glob(f"{tempfile.gettempdir()}/interview-audio-*")) == before
