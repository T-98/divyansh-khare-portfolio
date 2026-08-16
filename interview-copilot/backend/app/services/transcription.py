"""Speech-to-text.

Batch upload for the MVP: the browser records with MediaRecorder, POSTs the
blob, we hand it to OpenAI and return text. Everything sits behind
`Transcriber`, so a Realtime/WebSocket implementation can replace it later
without the API or the UI changing.

Audio is never persisted. The temp file exists only for the duration of the
call and is removed in a `finally`, including on failure.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..config import get_settings

logger = logging.getLogger(__name__)

# MediaRecorder emits webm/ogg on Chromium and mp4 on Safari.
_EXTENSIONS = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/m4a": ".m4a",
}

MIN_AUDIO_BYTES = 512


class TranscriptionError(RuntimeError):
    pass


@dataclass
class TranscriptionResult:
    text: str
    latency_ms: int
    model: str


def extension_for(content_type: str | None, filename: str | None) -> str:
    if filename and "." in filename:
        suffix = os.path.splitext(filename)[1].lower()
        if suffix in _EXTENSIONS.values():
            return suffix
    base = (content_type or "").split(";")[0].strip().lower()
    return _EXTENSIONS.get(base, ".webm")


class Transcriber(ABC):
    @abstractmethod
    async def transcribe(
        self, audio: bytes, *, content_type: str | None = None, filename: str | None = None
    ) -> TranscriptionResult: ...


class OpenAITranscriber(Transcriber):
    async def transcribe(
        self, audio: bytes, *, content_type: str | None = None, filename: str | None = None
    ) -> TranscriptionResult:
        settings = get_settings()
        if len(audio) < MIN_AUDIO_BYTES:
            raise TranscriptionError("recording too short")
        if len(audio) > settings.max_transcribe_bytes:
            raise TranscriptionError("recording too large")

        from ..agents.llm import get_client

        client = await get_client()
        suffix = extension_for(content_type, filename)
        started = time.perf_counter()

        handle, path = tempfile.mkstemp(suffix=suffix, prefix="interview-audio-")
        try:
            with os.fdopen(handle, "wb") as sink:
                sink.write(audio)

            model = settings.transcribe_model
            try:
                text = await self._call(client, path, model, settings.transcribe_timeout_s)
            except Exception as exc:  # noqa: BLE001
                if not _is_model_error(exc) or model == settings.fallback_transcribe_model:
                    raise TranscriptionError(str(exc)) from exc
                logger.warning("transcribe_model_rejected", extra={"model": model})
                model = settings.fallback_transcribe_model
                try:
                    text = await self._call(client, path, model, settings.transcribe_timeout_s)
                except Exception as inner:  # noqa: BLE001
                    raise TranscriptionError(str(inner)) from inner
        finally:
            # Raw audio never outlives the request.
            try:
                os.remove(path)
            except OSError:
                logger.warning("temp_audio_cleanup_failed", extra={"path": path})

        return TranscriptionResult(
            text=text.strip(),
            latency_ms=int((time.perf_counter() - started) * 1000),
            model=model,
        )

    @staticmethod
    async def _call(client, path: str, model: str, timeout: float) -> str:
        # The handle must stay open across the await, and must close after it.
        with open(path, "rb") as handle:
            result = await asyncio.wait_for(
                client.audio.transcriptions.create(model=model, file=handle),
                timeout=timeout,
            )
        return getattr(result, "text", "") or ""


def _is_model_error(exc: Exception) -> bool:
    from ..agents.llm import MODEL_ERROR_MARKERS

    text = str(exc).lower()
    return any(marker in text for marker in MODEL_ERROR_MARKERS)


_default: Transcriber | None = None


def get_transcriber() -> Transcriber:
    global _default
    if _default is None:
        _default = OpenAITranscriber()
    return _default


def set_transcriber(transcriber: Transcriber | None) -> None:
    """Swap the implementation (tests, or a future Realtime transcriber)."""
    global _default
    _default = transcriber
