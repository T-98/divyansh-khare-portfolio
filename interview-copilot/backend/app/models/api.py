"""Request / response DTOs for the HTTP layer."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .interview import InterviewResponse, InterviewState


class CreateSessionResponse(BaseModel):
    session_id: str
    created_at: datetime


class MessageRequest(BaseModel):
    text: str = Field(min_length=1)


class TimingBreakdown(BaseModel):
    router_latency_ms: int = 0
    specialist_latency_ms: int = 0
    editor_latency_ms: int = 0
    total_latency_ms: int = 0


class DebugInfo(BaseModel):
    """Everything the debug drawer renders. Never required by the UI."""

    request_id: str
    mode: str
    domains: list[str] = Field(default_factory=list)
    specialists: list[str] = Field(default_factory=list)
    router_model: str = ""
    specialist_model: str = ""
    editor_model: str = ""
    timings: TimingBreakdown = Field(default_factory=TimingBreakdown)
    routing: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)
    state_delta: dict[str, Any] = Field(default_factory=dict)
    specialist_output: dict[str, str] = Field(default_factory=dict)
    fallback_used: list[str] = Field(default_factory=list)
    quality_notes: list[str] = Field(default_factory=list)
    router_skipped: bool = False
    persistence_ok: bool = True


class MessageResponse(BaseModel):
    """Flat shape matching the documented API, plus an optional debug block."""

    session_id: str
    turn: int
    say: str
    path: list[str] = Field(default_factory=list)
    build: list[str] = Field(default_factory=list)
    push: str | None = None
    next_probe: str | None = None
    mode: str
    latency_ms: int
    answer_summary: str = ""
    warning: str | None = None
    debug: DebugInfo | None = None

    @classmethod
    def build_from(
        cls,
        *,
        session_id: str,
        turn: int,
        response: InterviewResponse,
        latency_ms: int,
        debug: DebugInfo | None,
        warning: str | None = None,
    ) -> "MessageResponse":
        return cls(
            session_id=session_id,
            turn=turn,
            say=response.say,
            path=response.path,
            build=response.build,
            push=response.push or None,
            next_probe=response.next_probe or None,
            mode=response.response_mode,
            latency_ms=latency_ms,
            answer_summary=response.answer_summary,
            warning=warning,
            debug=debug,
        )


class TurnSummary(BaseModel):
    turn: int
    interviewer_text: str
    say: str
    path: list[str] = Field(default_factory=list)
    build: list[str] = Field(default_factory=list)
    push: str | None = None
    next_probe: str | None = None
    mode: str
    latency_ms: int
    created_at: datetime


class SessionDetail(BaseModel):
    session_id: str
    created_at: datetime
    turn_count: int
    turns: list[TurnSummary] = Field(default_factory=list)
    state: InterviewState


class TranscriptionResponse(BaseModel):
    text: str
    latency_ms: int
    model: str


class HealthResponse(BaseModel):
    status: str
    openai_key_configured: bool
    models: dict[str, str]
    persistence: str
