"""Audio upload → text. The API key never leaves the backend."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..config import get_settings
from ..models.api import TranscriptionResponse
from ..services.transcription import TranscriptionError, get_transcriber

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["transcribe"])


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(audio: UploadFile = File(...)) -> TranscriptionResponse:
    settings = get_settings()
    data = await audio.read()

    if not data:
        raise HTTPException(status_code=422, detail="empty audio upload")
    if len(data) > settings.max_transcribe_bytes:
        raise HTTPException(status_code=413, detail="recording too large")

    try:
        result = await get_transcriber().transcribe(
            data, content_type=audio.content_type, filename=audio.filename
        )
    except TranscriptionError as exc:
        logger.warning("transcription_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=422, detail=f"transcription failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("transcription_error")
        raise HTTPException(status_code=502, detail="transcription unavailable") from exc

    logger.info(
        "transcription_complete",
        extra={"transcription_latency_ms": result.latency_ms, "model": result.model},
    )
    return TranscriptionResponse(
        text=result.text, latency_ms=result.latency_ms, model=result.model
    )
