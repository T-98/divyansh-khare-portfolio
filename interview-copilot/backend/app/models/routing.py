"""Router output — the classifier that decides who answers, not what is said."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal[
    "concept",
    "integration_discovery",
    "integration_implementation",
    "scenario",
    "incident",
    "debugging",
    "screen_share",
    "customer_requirements",
    "agent_systems",
    "resume_deep_dive",
    "followup",
]

Domain = Literal["integration", "agents", "reliability", "customer_implementation"]

Complexity = Literal["simple", "medium", "deep"]
ResponseBudget = Literal["short", "medium", "walkthrough"]

MODES: tuple[str, ...] = (
    "concept",
    "integration_discovery",
    "integration_implementation",
    "scenario",
    "incident",
    "debugging",
    "screen_share",
    "customer_requirements",
    "agent_systems",
    "resume_deep_dive",
    "followup",
)

DOMAINS: tuple[str, ...] = (
    "integration",
    "agents",
    "reliability",
    "customer_implementation",
)


class RoutingDecision(BaseModel):
    """Structured classification of one interviewer turn.

    The router never answers the interviewer. It only decides mode, domains and
    budget, and surfaces the explicit sub-questions the editor must cover.
    """

    mode: Mode
    domains: list[Domain] = Field(default_factory=list)
    complexity: Complexity = "medium"
    is_followup: bool = False
    changes_prior_assumption: bool = False
    explicit_subquestions: list[str] = Field(default_factory=list)
    interviewer_is_testing: str = ""
    response_budget: ResponseBudget = "medium"
    needs_second_specialist: bool = False
    likely_next_probe: str | None = None
