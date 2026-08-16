"""Session and message endpoints."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..models.api import (
    CreateSessionResponse,
    MessageRequest,
    MessageResponse,
    SessionDetail,
    TurnSummary,
)
from ..models.interview import InterviewState
from ..services.orchestrator import Orchestrator, SessionNotFound, TurnFailed

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


@router.post("", response_model=CreateSessionResponse, status_code=201)
@router.post("/", response_model=CreateSessionResponse, status_code=201, include_in_schema=False)
async def create_session(request: Request) -> CreateSessionResponse:
    record = await _orchestrator(request).create_session()
    return CreateSessionResponse(session_id=record.session_id, created_at=record.created_at)


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, request: Request) -> SessionDetail:
    store = request.app.state.store
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    turns = await store.list_turns(session_id)
    state = await store.get_state(session_id) or InterviewState(session_id=session_id)
    return SessionDetail(
        session_id=session.session_id,
        created_at=session.created_at,
        turn_count=len(turns),
        state=state,
        turns=[
            TurnSummary(
                turn=turn.turn_number,
                interviewer_text=turn.interviewer_text,
                say=turn.response.say,
                path=turn.response.path,
                build=turn.response.build,
                push=turn.response.push,
                next_probe=turn.response.next_probe,
                mode=turn.mode,
                latency_ms=turn.latency_ms,
                created_at=turn.created_at,
            )
            for turn in turns
        ],
    )


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request) -> None:
    deleted = await request.app.state.store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")


@router.post("/{session_id}/messages", response_model=MessageResponse)
async def post_message(
    session_id: str, payload: MessageRequest, request: Request
) -> MessageResponse:
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text must not be empty")
    try:
        return await _orchestrator(request).handle_message(session_id, text)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except TurnFailed as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/{session_id}/messages/stream")
async def stream_message(session_id: str, payload: MessageRequest, request: Request):
    """Server-sent events carrying the same turn, opening line first.

    The blocking endpoint above is the documented contract and is what the evals
    use. This one exists because three sequential model calls cannot put text on
    screen in two seconds any other way.
    """
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text must not be empty")

    orchestrator = _orchestrator(request)
    if await request.app.state.store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")

    async def events():
        try:
            async for event in orchestrator.stream_message(session_id, text):
                yield _sse(event)
        except SessionNotFound:
            yield _sse({"type": "error", "message": "session not found"})
        except Exception as exc:  # noqa: BLE001 — the stream must always close cleanly
            logger.exception("stream_failed", extra={"session_id": session_id})
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
