"""Final response editor — the only agent whose words reach the candidate.

Runs in two shapes off one prompt: a blocking structured call (used by the
documented JSON endpoint and the evals) and a streaming call (used by the live
UI, so the spoken opening lands while the rest is still generating).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from ..config import get_settings
from ..models.interview import InterviewResponse, InterviewState, StateDelta
from ..models.routing import RoutingDecision
from ..services.partial_json import partial_string_field
from ..services.state import render_state_for_prompt
from .llm import CallMeta, LLMError, parse_or_raise, stream_structured_call, structured_call
from .prompt_loader import editor_prompt

logger = logging.getLogger(__name__)

_BUDGET_HINT = {
    "short": "40-100 words total across SAY and BUILD.",
    "medium": "100-220 words total across SAY and BUILD.",
    "walkthrough": "200-450 words total; this one is allowed to be a real walkthrough.",
}


def build_payload(
    text: str,
    decision: RoutingDecision,
    state: InterviewState,
    specialist_outputs: dict[str, str],
) -> str:
    subquestions = (
        "\n".join(f"- {q}" for q in decision.explicit_subquestions) or "- (single question)"
    )
    lines = [
        "INTERVIEWER (transcribed):",
        text,
        "",
        "ROUTING:",
        f"  mode: {decision.mode}",
        f"  domains: {', '.join(decision.domains)}",
        f"  complexity: {decision.complexity}",
        f"  is_followup: {decision.is_followup}",
        f"  changes_prior_assumption: {decision.changes_prior_assumption}",
        f"  interviewer_is_testing: {decision.interviewer_is_testing}",
        f"  response_budget: {decision.response_budget} — "
        f"{_BUDGET_HINT.get(decision.response_budget, _BUDGET_HINT['medium'])}",
        "",
        "EVERY ONE OF THESE MUST BE ANSWERED:",
        subquestions,
        "",
        "INTERVIEW STATE:",
        render_state_for_prompt(state),
        "",
        "PREVIOUS ANSWER SUMMARY:",
        state.previous_answer_summary or "(none — first turn)",
    ]

    if specialist_outputs:
        lines.append("")
        lines.append("SPECIALIST NOTES (raw material — cut freely, do not quote):")
        for domain, output in specialist_outputs.items():
            lines.append("")
            lines.append(f"--- {domain} ---")
            lines.append(output)
    else:
        lines += [
            "",
            "SPECIALIST NOTES: none available this turn. Answer from the routing "
            "decision and state, and stay conservative about specifics.",
        ]

    if decision.is_followup:
        lines += [
            "",
            "This is a FOLLOW-UP. SAY must start from the new constraint. Do not "
            "re-explain the scenario or repeat the previous answer's framing.",
        ]
    if decision.changes_prior_assumption:
        lines += [
            "",
            "The interviewer changed a constraint that can invalidate the previous "
            "recommendation. SAY must name what no longer holds before giving the "
            "revised move, and state_delta.invalidated_advice must be set.",
        ]
    if decision.likely_next_probe:
        lines += ["", f"Router's guess at the next probe: {decision.likely_next_probe}"]

    lines += ["", "Write the candidate's response now."]
    return "\n".join(lines)


async def edit(
    text: str,
    decision: RoutingDecision,
    state: InterviewState,
    specialist_outputs: dict[str, str],
) -> tuple[InterviewResponse, CallMeta]:
    settings = get_settings()
    response, meta = await structured_call(
        model=settings.editor_model,
        system=editor_prompt(),
        user=build_payload(text, decision, state, specialist_outputs),
        schema_model=InterviewResponse,
        schema_name="interview_response",
        timeout=settings.editor_timeout_s,
    )
    response.response_mode = response.response_mode or decision.mode
    return response, meta


async def edit_stream(
    text: str,
    decision: RoutingDecision,
    state: InterviewState,
    specialist_outputs: dict[str, str],
) -> AsyncIterator[tuple[str, Any]]:
    """Yield `("say", partial_text)` as the opening arrives, then `("final", response)`."""
    settings = get_settings()
    started = time.perf_counter()
    buffer: list[str] = []
    emitted = ""

    async for kind, payload in stream_structured_call(
        model=settings.editor_model,
        system=editor_prompt(),
        user=build_payload(text, decision, state, specialist_outputs),
        schema_model=InterviewResponse,
        schema_name="interview_response",
        timeout=settings.editor_timeout_s,
    ):
        if kind == "chunk":
            buffer.append(payload)
            say_so_far, _ = partial_string_field("".join(buffer), "say")
            if say_so_far and say_so_far != emitted:
                emitted = say_so_far
                yield "say", say_so_far
            continue

        response = parse_or_raise(InterviewResponse, payload, "interview_response")
        response.response_mode = response.response_mode or decision.mode
        meta = CallMeta(model=settings.editor_model)
        meta.latency_ms = int((time.perf_counter() - started) * 1000)
        yield "final", (response, meta)


async def emergency_answer(
    text: str,
    decision: RoutingDecision,
    state: InterviewState,
    specialist_outputs: dict[str, str],
) -> tuple[InterviewResponse, CallMeta]:
    """One direct call on the specialist model when the editor itself fails.

    Deliberately a single attempt. Stacking retries in front of a person who is
    mid-sentence in an interview is worse than degrading fast.
    """
    settings = get_settings()
    response, meta = await structured_call(
        model=settings.specialist_model,
        system=editor_prompt(),
        user=build_payload(text, decision, state, specialist_outputs),
        schema_model=InterviewResponse,
        schema_name="interview_response",
        timeout=settings.editor_timeout_s,
    )
    response.response_mode = response.response_mode or decision.mode
    meta.notes.append("editor failed; answered with specialist model")
    meta.fallback_used = True
    return response, meta


_LABELS = ("ANSWER", "REASONING", "MECHANICS", "DEEPER", "RISKS")


def parse_specialist_notes(text: str) -> dict[str, list[str]]:
    """Split labelled specialist notes into sections. Tolerant of missing labels."""
    pattern = re.compile(rf"^({'|'.join(_LABELS)})\s*:\s*", re.MULTILINE)
    matches = list(pattern.finditer(text))
    sections: dict[str, list[str]] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        lines = [
            re.sub(r"^[-*•\d.\s]+", "", line).strip()
            for line in body.splitlines()
            if line.strip()
        ]
        sections[match.group(1)] = [line for line in lines if line]
    return sections


def synthesize_from_specialist(
    specialist_outputs: dict[str, str],
    decision: RoutingDecision,
) -> InterviewResponse | None:
    """Last-resort answer built in Python from specialist notes — no model call.

    Reached only when both the editor and its fallback are unavailable. Rough,
    but a rough answer on screen beats an error while the interviewer waits.
    """
    if not specialist_outputs:
        return None
    merged: dict[str, list[str]] = {}
    for output in specialist_outputs.values():
        for label, lines in parse_specialist_notes(output).items():
            merged.setdefault(label, []).extend(lines)

    answer = " ".join(merged.get("ANSWER", []))
    if not answer:
        first = next(iter(specialist_outputs.values())).strip()
        answer = " ".join(first.split()[:60])
    if not answer:
        return None

    return InterviewResponse(
        say=answer,
        path=[step for step in merged.get("REASONING", [])][:6],
        build=merged.get("MECHANICS", [])[:6],
        push=" ".join(merged.get("DEEPER", [])) or None,
        next_probe=decision.likely_next_probe,
        response_mode=decision.mode,
        answer_summary=answer[:400],
        state_delta=StateDelta(),
    )


__all__ = [
    "LLMError",
    "build_payload",
    "edit",
    "edit_stream",
    "emergency_answer",
    "parse_specialist_notes",
    "synthesize_from_specialist",
]
