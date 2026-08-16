"""Turn orchestration: route → specialist(s) → editor → quality gate → persist.

Default live path is three model calls. Two specialists run concurrently when
the router says the question genuinely mixes domains; chips skip the router
entirely. Every stage degrades rather than failing the turn, because the failure
mode that matters is "nothing on screen while the interviewer waits".
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ..agents import editor as editor_agent
from ..agents import router as router_agent
from ..agents import specialists as specialist_agent
from ..agents.llm import CallMeta, LLMError
from ..config import get_settings
from ..models.api import DebugInfo, MessageResponse, TimingBreakdown
from ..models.interview import InterviewResponse, InterviewState, TurnRecord
from ..models.routing import RoutingDecision
from ..persistence.base import SessionStore
from .quality import run_quality_gate
from .state import apply_delta

logger = logging.getLogger("interview.turn")


class SessionNotFound(LookupError):
    pass


class TurnFailed(RuntimeError):
    pass


class Orchestrator:
    def __init__(self, store: SessionStore) -> None:
        self._store = store

    # ------------------------------------------------------------------ setup

    async def create_session(self) -> Any:
        return await self._store.create_session(uuid.uuid4().hex[:16])

    async def _load(self, session_id: str) -> tuple[InterviewState, list[str]]:
        session = await self._store.get_session(session_id)
        if session is None:
            raise SessionNotFound(session_id)
        state = await self._store.get_state(session_id) or InterviewState(session_id=session_id)
        turns = await self._store.list_turns(session_id)
        previous_domains = turns[-1].domains if turns else []
        return state, previous_domains

    # ------------------------------------------------------------------ stages

    async def _route(
        self, text: str, state: InterviewState, previous_domains: list[str]
    ) -> tuple[RoutingDecision, int, bool, list[str]]:
        chip_decision = router_agent.deterministic_route(text, state, previous_domains)
        if chip_decision is not None:
            return chip_decision, 0, True, []

        started = time.perf_counter()
        decision, meta = await router_agent.route(text, state)
        elapsed = meta.latency_ms or int((time.perf_counter() - started) * 1000)
        return decision, elapsed, False, list(meta.notes)

    async def _finalise(
        self,
        *,
        text: str,
        decision: RoutingDecision,
        specialists: specialist_agent.SpecialistResult,
        response: InterviewResponse,
        state: InterviewState,
        session_id: str,
        turn_number: int,
        started: float,
        router_ms: int,
        editor_ms: int,
        router_skipped: bool,
        fallbacks: list[str],
        request_id: str,
    ) -> MessageResponse:
        cleaned, quality_notes = run_quality_gate(
            response,
            budget=decision.response_budget,
            subquestions=decision.explicit_subquestions,
        )

        new_state = apply_delta(
            state,
            cleaned.state_delta,
            decision,
            answer_summary=cleaned.answer_summary,
        )
        new_state.turn_number = turn_number

        total_ms = int((time.perf_counter() - started) * 1000)
        persistence_ok = True
        warning: str | None = None
        try:
            await self._store.append_turn(
                TurnRecord(
                    session_id=session_id,
                    turn_number=turn_number,
                    interviewer_text=text,
                    response=cleaned,
                    mode=decision.mode,
                    domains=list(decision.domains),
                    specialists=specialists.selected,
                    latency_ms=total_ms,
                )
            )
            await self._store.save_state(new_state)
        except Exception as exc:  # noqa: BLE001 — surfaced, never swallowed
            persistence_ok = False
            warning = "Session not saved — follow-ups may lose earlier constraints."
            fallbacks.append(f"persistence: {exc}")
            logger.error("persistence_failed", extra={"session_id": session_id, "error": str(exc)})

        settings = get_settings()
        debug = DebugInfo(
            request_id=request_id,
            mode=decision.mode,
            domains=list(decision.domains),
            specialists=specialists.selected,
            router_model="(deterministic)" if router_skipped else settings.router_model,
            specialist_model=specialists.models[0] if specialists.models else "",
            editor_model=settings.editor_model,
            timings=TimingBreakdown(
                router_latency_ms=router_ms,
                specialist_latency_ms=specialists.latency_ms,
                editor_latency_ms=editor_ms,
                total_latency_ms=total_ms,
            ),
            routing=decision.model_dump(),
            state=new_state.model_dump(),
            state_delta=cleaned.state_delta.model_dump(),
            specialist_output=specialists.outputs if settings.debug_agent_output else {},
            fallback_used=fallbacks + specialists.failures,
            quality_notes=quality_notes,
            router_skipped=router_skipped,
            persistence_ok=persistence_ok,
        )

        logger.info(
            "turn_complete",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "turn_number": turn_number,
                "mode": decision.mode,
                "domains": list(decision.domains),
                "selected_specialists": specialists.selected,
                "router_model": debug.router_model,
                "specialist_model": debug.specialist_model,
                "editor_model": debug.editor_model,
                "router_latency_ms": router_ms,
                "specialist_latency_ms": specialists.latency_ms,
                "editor_latency_ms": editor_ms,
                "total_latency_ms": total_ms,
                "fallback_used": debug.fallback_used,
                "persistence_ok": persistence_ok,
            },
        )

        return MessageResponse.build_from(
            session_id=session_id,
            turn=turn_number,
            response=cleaned,
            latency_ms=total_ms,
            debug=debug,
            warning=warning,
        )

    # ------------------------------------------------------------------ blocking

    async def handle_message(self, session_id: str, text: str) -> MessageResponse:
        request_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        state, previous_domains = await self._load(session_id)
        turn_number = state.turn_number + 1
        fallbacks: list[str] = []

        decision, router_ms, router_skipped, router_notes = await self._route(
            text, state, previous_domains
        )
        fallbacks += router_notes

        editor_text = router_agent.chip_intent(text) or text
        specialists = await specialist_agent.run_specialists(editor_text, decision, state)

        editor_started = time.perf_counter()
        try:
            response, meta = await editor_agent.edit(
                editor_text, decision, state, specialists.outputs
            )
            if meta.fallback_used:
                fallbacks += meta.notes
        except LLMError as exc:
            fallbacks.append(f"editor: {exc}")
            response, meta = await self._recover(editor_text, decision, state, specialists, fallbacks)
        editor_ms = meta.latency_ms or int((time.perf_counter() - editor_started) * 1000)

        return await self._finalise(
            text=text,
            decision=decision,
            specialists=specialists,
            response=response,
            state=state,
            session_id=session_id,
            turn_number=turn_number,
            started=started,
            router_ms=router_ms,
            editor_ms=editor_ms,
            router_skipped=router_skipped,
            fallbacks=fallbacks,
            request_id=request_id,
        )

    async def _recover(
        self,
        text: str,
        decision: RoutingDecision,
        state: InterviewState,
        specialists: specialist_agent.SpecialistResult,
        fallbacks: list[str],
    ) -> tuple[InterviewResponse, CallMeta]:
        """Editor failed: one direct call, then a Python-only synthesis."""
        try:
            return await editor_agent.emergency_answer(
                text, decision, state, specialists.outputs
            )
        except LLMError as exc:
            fallbacks.append(f"emergency editor: {exc}")

        synthesised = editor_agent.synthesize_from_specialist(specialists.outputs, decision)
        if synthesised is None:
            raise TurnFailed("router, specialists and editor all failed")
        fallbacks.append("answered from specialist notes without an editor pass")
        return synthesised, CallMeta(model="(none)", fallback_used=True)

    # ------------------------------------------------------------------ streaming

    async def stream_message(self, session_id: str, text: str) -> AsyncIterator[dict[str, Any]]:
        """Same pipeline, but emits the spoken opening as soon as it exists."""
        request_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        state, previous_domains = await self._load(session_id)
        turn_number = state.turn_number + 1
        fallbacks: list[str] = []

        decision, router_ms, router_skipped, router_notes = await self._route(
            text, state, previous_domains
        )
        fallbacks += router_notes
        yield {
            "type": "routing",
            "mode": decision.mode,
            "domains": list(decision.domains),
            "budget": decision.response_budget,
            "router_latency_ms": router_ms,
            "router_skipped": router_skipped,
        }

        editor_text = router_agent.chip_intent(text) or text
        specialists = await specialist_agent.run_specialists(editor_text, decision, state)
        yield {
            "type": "specialists",
            "selected": specialists.selected,
            "specialist_latency_ms": specialists.latency_ms,
            "failures": specialists.failures,
        }

        editor_started = time.perf_counter()
        response: InterviewResponse | None = None
        meta = CallMeta(model=get_settings().editor_model)
        try:
            async for kind, payload in editor_agent.edit_stream(
                editor_text, decision, state, specialists.outputs
            ):
                if kind == "say":
                    yield {"type": "say", "text": payload}
                else:
                    response, meta = payload
        except LLMError as exc:
            fallbacks.append(f"editor stream: {exc}")

        if response is None:
            try:
                response, meta = await self._recover(
                    editor_text, decision, state, specialists, fallbacks
                )
            except TurnFailed as exc:
                yield {"type": "error", "message": str(exc)}
                return
            yield {"type": "say", "text": response.say}

        editor_ms = meta.latency_ms or int((time.perf_counter() - editor_started) * 1000)

        final = await self._finalise(
            text=text,
            decision=decision,
            specialists=specialists,
            response=response,
            state=state,
            session_id=session_id,
            turn_number=turn_number,
            started=started,
            router_ms=router_ms,
            editor_ms=editor_ms,
            router_skipped=router_skipped,
            fallbacks=fallbacks,
            request_id=request_id,
        )
        yield {"type": "final", "payload": final.model_dump(mode="json")}
