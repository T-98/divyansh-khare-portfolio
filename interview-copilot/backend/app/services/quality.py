"""Deterministic quality gate.

Anti-repetition is a hard product requirement, so it runs in Python on every
turn — no extra model call, no extra latency. Section ownership is:

    SAY   immediate answer      PATH  direction only
    BUILD mechanics not in SAY  PUSH  a genuinely deeper layer
    NEXT  one likely probe

Anything in a later section that merely paraphrases an earlier one is dropped.
"""

from __future__ import annotations

import re

from ..models.interview import InterviewResponse

_STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those of to in on at by for with
    from into about as is are was were be been being it its it's you your we our i
    they them their he she his her would should could can will do does did not no
    have has had s t re ll ve m d so just also very really only more most other
    """.split()
)

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9'\-]*")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

# Above this token-overlap two fragments are making the same point.
DUPLICATE_THRESHOLD = 0.7
# PUSH is allowed to touch earlier ground; only near-identity is repetition.
PUSH_DUPLICATE_THRESHOLD = 0.8

BUDGET_WORD_RANGES: dict[str, tuple[int, int]] = {
    "short": (40, 140),
    "medium": (100, 260),
    "walkthrough": (200, 480),
}


def content_tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS and len(w) > 2}


def similarity(a: str, b: str) -> float:
    """Token-overlap ratio against the smaller fragment.

    Deliberately asymmetric-friendly: a short bullet fully contained in a long
    sentence scores 1.0, which is exactly the repetition we want to catch.
    """
    ta, tb = content_tokens(a), content_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text.strip()) if s.strip()]


def is_duplicate(candidate: str, priors: list[str], threshold: float = DUPLICATE_THRESHOLD) -> bool:
    return any(similarity(candidate, prior) >= threshold for prior in priors)


def word_count(response: InterviewResponse) -> int:
    parts = [response.say, " ".join(response.path), " ".join(response.build)]
    if response.push:
        parts.append(response.push)
    return len(" ".join(parts).split())


def dedupe_response(response: InterviewResponse) -> tuple[InterviewResponse, list[str]]:
    """Strip cross-section repetition. Returns the cleaned response plus notes."""
    notes: list[str] = []
    cleaned = response.model_copy(deep=True)

    say_sentences = sentences(cleaned.say)

    kept_path: list[str] = []
    for step in cleaned.path:
        step = step.strip()
        if not step:
            continue
        if is_duplicate(step, kept_path):
            notes.append(f"dropped duplicate PATH step: {step!r}")
            continue
        kept_path.append(step)
    cleaned.path = kept_path

    # BUILD must not restate SAY. PATH is only a direction line, so a BUILD
    # bullet that expands a PATH step is legitimate and is not compared.
    kept_build: list[str] = []
    for bullet in cleaned.build:
        bullet = bullet.strip()
        if not bullet:
            continue
        if is_duplicate(bullet, say_sentences):
            notes.append(f"dropped BUILD bullet already stated in SAY: {bullet!r}")
            continue
        if is_duplicate(bullet, kept_build):
            notes.append(f"dropped duplicate BUILD bullet: {bullet!r}")
            continue
        kept_build.append(bullet)
    cleaned.build = kept_build

    if cleaned.push:
        prior = say_sentences + cleaned.build
        push_sentences = [
            s
            for s in sentences(cleaned.push)
            if not is_duplicate(s, prior, PUSH_DUPLICATE_THRESHOLD)
        ]
        if not push_sentences:
            notes.append("dropped IF THEY PUSH — it only restated SAY/BUILD")
            cleaned.push = None
        elif len(push_sentences) != len(sentences(cleaned.push)):
            notes.append("trimmed repeated sentences from IF THEY PUSH")
            cleaned.push = " ".join(push_sentences)

    if cleaned.next_probe:
        prior = say_sentences + cleaned.build + ([cleaned.push] if cleaned.push else [])
        if is_duplicate(cleaned.next_probe, prior, PUSH_DUPLICATE_THRESHOLD):
            notes.append("dropped NEXT — it restated earlier content")
            cleaned.next_probe = None

    return cleaned, notes


def budget_notes(response: InterviewResponse, budget: str) -> list[str]:
    """Advisory only. Budgets are guidance in the spec, never a hard validator."""
    low, high = BUDGET_WORD_RANGES.get(budget, BUDGET_WORD_RANGES["medium"])
    count = word_count(response)
    if count > high * 1.3:
        return [f"over budget: {count} words vs {budget} target {low}-{high}"]
    if count < low * 0.5:
        return [f"under budget: {count} words vs {budget} target {low}-{high}"]
    return []


def coverage_notes(response: InterviewResponse, subquestions: list[str]) -> list[str]:
    """Flag explicit sub-questions with no lexical trace in the answer.

    A heuristic for the debug drawer, not a gate — it is here so prompt tuning
    before the interview has a signal to work against.
    """
    if not subquestions:
        return []
    body = " ".join([response.say, " ".join(response.path), " ".join(response.build), response.push or ""])
    body_tokens = content_tokens(body)
    missing = []
    for question in subquestions:
        q_tokens = content_tokens(question)
        if not q_tokens:
            continue
        if len(q_tokens & body_tokens) / len(q_tokens) < 0.34:
            missing.append(question)
    return [f"possible uncovered sub-question: {q!r}" for q in missing]


def run_quality_gate(
    response: InterviewResponse,
    *,
    budget: str = "medium",
    subquestions: list[str] | None = None,
) -> tuple[InterviewResponse, list[str]]:
    cleaned, notes = dedupe_response(response)
    notes += budget_notes(cleaned, budget)
    notes += coverage_notes(cleaned, subquestions or [])
    return cleaned, notes
