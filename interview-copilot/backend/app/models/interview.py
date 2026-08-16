"""Interview state, editor output, and persisted turn records."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InterviewState(BaseModel):
    """Structured memory for one interview session.

    Raw chat history alone loses the constraints an interviewer stacks up over
    several turns ("the provider has no idempotency", "you cannot query it
    afterwards"). This model carries those forward explicitly so a follow-up
    zooms into the new constraint instead of restarting the scenario.
    """

    session_id: str
    turn_number: int = 0

    current_topic: str | None = None
    current_mode: str | None = None
    current_scenario: str | None = None

    established_assumptions: list[str] = Field(default_factory=list)
    interviewer_constraints: list[str] = Field(default_factory=list)
    accepted_tradeoffs: list[str] = Field(default_factory=list)

    systems_mentioned: list[str] = Field(default_factory=list)
    technologies_mentioned: list[str] = Field(default_factory=list)

    source_of_truth_decisions: list[str] = Field(default_factory=list)
    security_boundaries: list[str] = Field(default_factory=list)

    previous_candidate_position: str | None = None
    previous_answer_summary: str | None = None

    unresolved_questions: list[str] = Field(default_factory=list)
    candidate_claims: list[str] = Field(default_factory=list)


class StateDelta(BaseModel):
    """What the editor learned this turn.

    Typed rather than a free-form dict: strict structured output cannot express
    an open object, and a typed delta makes the merge testable. Serialised as a
    plain dict on the wire, so it still matches the documented API shape.
    """

    current_topic: str | None = None
    current_scenario: str | None = None

    new_assumptions: list[str] = Field(default_factory=list)
    new_constraints: list[str] = Field(default_factory=list)
    new_tradeoffs: list[str] = Field(default_factory=list)

    new_systems: list[str] = Field(default_factory=list)
    new_technologies: list[str] = Field(default_factory=list)

    new_source_of_truth_decisions: list[str] = Field(default_factory=list)
    new_security_boundaries: list[str] = Field(default_factory=list)

    candidate_position: str | None = None

    new_unresolved_questions: list[str] = Field(default_factory=list)
    resolved_questions: list[str] = Field(default_factory=list)
    new_candidate_claims: list[str] = Field(default_factory=list)

    invalidated_advice: str | None = None


class InterviewResponse(BaseModel):
    """The only thing the candidate ever sees.

    Field order matters: `say` is first so it is the first thing to arrive when
    the editor response is streamed.
    """

    say: str
    path: list[str] = Field(default_factory=list)
    build: list[str] = Field(default_factory=list)
    push: str | None = None
    next_probe: str | None = None
    response_mode: str = "scenario"
    answer_summary: str = ""
    state_delta: StateDelta = Field(default_factory=StateDelta)


class TurnRecord(BaseModel):
    """One persisted interviewer question + assistant answer."""

    session_id: str
    turn_number: int
    interviewer_text: str
    response: InterviewResponse
    mode: str
    domains: list[str] = Field(default_factory=list)
    specialists: list[str] = Field(default_factory=list)
    latency_ms: int = 0
    created_at: datetime = Field(default_factory=_utcnow)


class SessionRecord(BaseModel):
    session_id: str
    created_at: datetime = Field(default_factory=_utcnow)
    turn_count: int = 0
