"""Specialist fan-out.

One specialist is the default. Two run concurrently when the router says the
question genuinely mixes domains. Never more — a third opinion costs live
latency and the editor has to reconcile it anyway.

Specialists return notes, never candidate-facing text.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from ..config import get_settings
from ..models.interview import InterviewState
from ..models.routing import RoutingDecision
from ..services.state import render_state_for_prompt
from .llm import LLMError, text_call
from .prompt_loader import specialist_prompt

logger = logging.getLogger(__name__)

MAX_SPECIALISTS = 2

_COMPLEXITY_TOKENS = {"simple": 400, "medium": 700, "deep": 1100}


@dataclass
class SpecialistResult:
    outputs: dict[str, str] = field(default_factory=dict)
    selected: list[str] = field(default_factory=list)
    latency_ms: int = 0
    failures: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    fallback_used: bool = False


def select_specialists(decision: RoutingDecision) -> list[str]:
    """Domains to actually run. Deterministic, and hard-capped at two."""
    domains = list(dict.fromkeys(decision.domains)) or ["integration"]
    if decision.needs_second_specialist and len(domains) >= 2:
        return domains[:MAX_SPECIALISTS]
    return domains[:1]


def model_for(decision: RoutingDecision, selected: list[str]) -> str:
    """Escalate to the strongest model only where it earns its latency.

    That means a genuinely deep question answered by a single specialist. A
    two-specialist turn already costs the most it should; paying the deep model
    twice in parallel is how a live answer arrives too late to use.
    """
    settings = get_settings()
    if decision.complexity == "deep" and len(selected) == 1:
        return settings.deep_model
    return settings.specialist_model


def _user_payload(
    text: str,
    decision: RoutingDecision,
    state: InterviewState,
    partner: str | None,
) -> str:
    subquestions = "\n".join(f"- {q}" for q in decision.explicit_subquestions) or "- (single question)"
    lines = [
        "INTERVIEWER (transcribed):",
        text,
        "",
        f"MODE: {decision.mode}",
        f"COMPLEXITY: {decision.complexity}",
        f"RESPONSE BUDGET: {decision.response_budget}",
        f"INTERVIEWER IS TESTING: {decision.interviewer_is_testing}",
        "",
        "EXPLICIT SUB-QUESTIONS THE ANSWER MUST COVER:",
        subquestions,
        "",
        "INTERVIEW STATE:",
        render_state_for_prompt(state),
        "",
        "PREVIOUS ANSWER SUMMARY:",
        state.previous_answer_summary or "(none — first turn)",
    ]
    if decision.is_followup:
        lines += [
            "",
            "This is a FOLLOW-UP. Do not restart the scenario. Zoom into what changed.",
        ]
    if decision.changes_prior_assumption:
        lines += [
            "",
            "The interviewer just changed a constraint. Say plainly which part of the "
            "previous recommendation no longer holds, and what replaces it.",
        ]
    if partner:
        lines += [
            "",
            f"A {partner} specialist is answering the other half of this question in "
            "parallel. Stay in your lane; do not duplicate their ground.",
        ]
    return "\n".join(lines)


async def _run_one(
    domain: str,
    text: str,
    decision: RoutingDecision,
    state: InterviewState,
    partner: str | None,
    model: str,
) -> tuple[str, str, bool]:
    settings = get_settings()
    output, meta = await text_call(
        model=model,
        system=specialist_prompt(domain),
        user=_user_payload(text, decision, state, partner),
        timeout=settings.specialist_timeout_s,
        max_tokens=_COMPLEXITY_TOKENS.get(decision.complexity, 700),
    )
    return domain, output, meta.fallback_used


async def run_specialists(
    text: str,
    decision: RoutingDecision,
    state: InterviewState,
) -> SpecialistResult:
    """Run the selected specialists concurrently. Partial failure is survivable."""
    selected = select_specialists(decision)
    result = SpecialistResult(selected=selected)
    model = model_for(decision, selected)
    result.models = [model] * len(selected)

    started = time.perf_counter()
    tasks = [
        _run_one(
            domain,
            text,
            decision,
            state,
            partner=next((d for d in selected if d != domain), None),
            model=model,
        )
        for domain in selected
    ]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    result.latency_ms = int((time.perf_counter() - started) * 1000)

    for domain, outcome in zip(selected, gathered, strict=True):
        if isinstance(outcome, BaseException):
            message = str(outcome) if isinstance(outcome, LLMError) else repr(outcome)
            logger.warning("specialist_failed", extra={"domain": domain, "error": message})
            result.failures.append(f"{domain}: {message}")
            continue
        _, output, fallback = outcome
        if output:
            result.outputs[domain] = output
        result.fallback_used = result.fallback_used or fallback

    return result
