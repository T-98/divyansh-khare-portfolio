"""Mode classifier.

Two paths. Quick-command chips ("deeper", "debug", "screen") are routed in
Python — they carry no ambiguity, and skipping the classifier saves a whole
network round trip on the turns where the candidate is already mid-answer.
Everything else goes to the fast model.
"""

from __future__ import annotations

import logging

from ..config import get_settings
from ..models.interview import InterviewState
from ..models.routing import DOMAINS, RoutingDecision
from ..services.state import render_state_for_prompt
from .llm import CallMeta, LLMError, structured_call
from .prompt_loader import router_prompt

logger = logging.getLogger(__name__)

# mode, budget, domains, second-specialist
_CHIPS: dict[str, tuple[str, str, list[str], bool]] = {
    "deeper": ("followup", "medium", [], False),
    "technical": ("followup", "medium", [], False),
    "why": ("followup", "short", [], False),
    "failure": ("scenario", "medium", ["reliability"], False),
    "debug": ("debugging", "medium", ["reliability"], False),
    "scale": ("scenario", "medium", ["reliability"], False),
    "security": ("concept", "medium", [], False),
    "screen": ("screen_share", "walkthrough", ["integration", "customer_implementation"], True),
    "push": ("followup", "medium", [], False),
}

_CHIP_INTENT: dict[str, str] = {
    "deeper": "go one layer deeper on the same point",
    "technical": "give the concrete technical mechanics",
    "why": "explain why that is the right call",
    "failure": "walk through how this fails",
    "debug": "how you would debug this",
    "scale": "how this behaves under load",
    "security": "the security and authorization boundaries here",
    "screen": "walk through the exact implementation as if screen-sharing",
    "push": "the interviewer is pushing back on that answer",
}

_CHIP_PROBE: dict[str, str] = {
    "screen": "which part of that would you build first",
    "push": "are you sure that is the right tradeoff",
}


def chip_intent(text: str) -> str | None:
    """Expand a chip into the sentence the editor should treat as the question."""
    return _CHIP_INTENT.get(normalise_chip(text) or "")


def normalise_chip(text: str) -> str | None:
    token = text.strip().lower().strip(".!?,: ")
    return token if token in _CHIPS else None


def _domains_for_chip(
    chip: str, explicit: list[str], previous_domains: list[str], state: InterviewState
) -> list[str]:
    if explicit:
        return explicit
    carried = [d for d in previous_domains if d in DOMAINS][:2]
    if carried:
        return carried
    if chip == "security":
        return ["agents"] if state.current_mode == "agent_systems" else ["integration"]
    return ["integration"]


def deterministic_route(
    text: str,
    state: InterviewState,
    previous_domains: list[str] | None = None,
) -> RoutingDecision | None:
    """Route a quick-command chip without calling a model. None if not a chip."""
    chip = normalise_chip(text)
    if chip is None:
        return None
    if state.turn_number == 0 and chip not in ("screen", "security"):
        # A follow-up chip with nothing to follow up on: let the model handle it.
        return None

    mode, budget, explicit_domains, needs_second = _CHIPS[chip]
    domains = _domains_for_chip(chip, explicit_domains, previous_domains or [], state)

    return RoutingDecision(
        mode=mode,  # type: ignore[arg-type]
        domains=domains,  # type: ignore[arg-type]
        complexity="deep" if chip in ("deeper", "screen") else "medium",
        is_followup=chip != "screen" or state.turn_number > 0,
        changes_prior_assumption=False,
        explicit_subquestions=[_CHIP_INTENT[chip]],
        interviewer_is_testing=f"candidate can {_CHIP_INTENT[chip]} without restarting",
        response_budget=budget,  # type: ignore[arg-type]
        needs_second_specialist=needs_second,
        likely_next_probe=_CHIP_PROBE.get(chip),
    )


def sanitise(decision: RoutingDecision) -> RoutingDecision:
    """Enforce the invariants the orchestrator relies on.

    The router is a small fast model; trusting it to respect 'at most two
    specialists' is not a plan. Clamp deterministically instead.
    """
    cleaned = decision.model_copy(deep=True)

    seen: list[str] = []
    for domain in cleaned.domains:
        if domain in DOMAINS and domain not in seen:
            seen.append(domain)
    if not seen:
        seen = ["integration"]
    cleaned.domains = seen[:2]  # type: ignore[assignment]

    if len(cleaned.domains) < 2:
        cleaned.needs_second_specialist = False
    if cleaned.mode == "incident":
        cleaned.response_budget = "medium"
        if "reliability" in cleaned.domains:
            cleaned.domains = ["reliability"] + [  # type: ignore[assignment]
                d for d in cleaned.domains if d != "reliability"
            ]

    cleaned.explicit_subquestions = [
        q.strip() for q in cleaned.explicit_subquestions if q.strip()
    ][:6]
    if cleaned.likely_next_probe is not None and not cleaned.likely_next_probe.strip():
        cleaned.likely_next_probe = None

    return cleaned


def _user_payload(text: str, state: InterviewState) -> str:
    return (
        "INTERVIEWER (transcribed):\n"
        f"{text}\n\n"
        "INTERVIEW STATE:\n"
        f"{render_state_for_prompt(state)}\n\n"
        "PREVIOUS ANSWER SUMMARY:\n"
        f"{state.previous_answer_summary or '(none — first turn)'}\n\n"
        "Classify this turn."
    )


def fallback_decision(text: str, state: InterviewState) -> RoutingDecision:
    """Keyword routing used when the router model itself fails.

    Crude on purpose — its only job is to keep a live interview answerable.
    """
    lowered = text.lower()
    incident_words = ("down", "outage", "production", "unblock", "right now", "minutes", "users cannot")
    agent_words = ("agent", "tool call", "llm", "prompt", "rag", "hallucin", "model", "injection")
    reliability_words = ("429", "rate limit", "race", "timeout", "retry", "concurren", "rps", "latency")
    customer_words = ("customer", "client wants", "no api", "discovery", "requirements", "stakeholder")

    mode = "followup" if state.turn_number > 0 and len(text.split()) <= 12 else "scenario"
    domains = ["integration"]
    if any(word in lowered for word in incident_words):
        mode, domains = "incident", ["reliability"]
    elif any(word in lowered for word in agent_words):
        mode, domains = "agent_systems", ["agents"]
    elif any(word in lowered for word in reliability_words):
        domains = ["reliability"]
    elif any(word in lowered for word in customer_words):
        mode, domains = "customer_requirements", ["customer_implementation"]

    return RoutingDecision(
        mode=mode,  # type: ignore[arg-type]
        domains=domains,  # type: ignore[arg-type]
        complexity="medium",
        is_followup=state.turn_number > 0 and len(text.split()) <= 12,
        changes_prior_assumption=False,
        explicit_subquestions=[text.strip()[:200]],
        interviewer_is_testing="unclassified — router unavailable",
        response_budget="medium",
        needs_second_specialist=False,
        likely_next_probe=None,
    )


async def route(text: str, state: InterviewState) -> tuple[RoutingDecision, CallMeta]:
    """Classify one turn with the fast model, falling back to keywords."""
    settings = get_settings()
    try:
        decision, meta = await structured_call(
            model=settings.router_model,
            system=router_prompt(),
            user=_user_payload(text, state),
            schema_model=RoutingDecision,
            schema_name="routing_decision",
            timeout=settings.router_timeout_s,
        )
    except LLMError as exc:
        logger.warning("router_failed", extra={"error": str(exc)})
        meta = CallMeta(model=settings.router_model, fallback_used=True)
        meta.notes.append(f"router failed ({exc}); used keyword fallback")
        return fallback_decision(text, state), meta

    return sanitise(decision), meta
