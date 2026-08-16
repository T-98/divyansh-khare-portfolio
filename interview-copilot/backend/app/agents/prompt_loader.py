"""Loads and slices the prompt markdown.

`specialist-agents.md` is the single behavioural source of truth. Rather than
duplicating it — or sending all 16KB on every call — it is parsed into its
numbered top-level sections and each agent is composed from the sections it
actually needs. Editing the markdown changes behaviour; no Python change needed.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from ..config import PROMPTS_DIR

SPECIALIST_DOC = "specialist-agents.md"
ROUTER_DOC = "router.md"
EDITOR_DOC = "editor.md"

_SECTION_RE = re.compile(r"^#\s+(\d+)\.\s+(.+?)\s*$", re.MULTILINE)

# Section numbers in specialist-agents.md.
SHARED_SECTIONS = (1, 2, 3, 4, 5)
CONTINUITY_SECTIONS = (11, 12, 13, 14)
MODE_SECTION = (10,)
EDITOR_CHECKLIST = (15,)

SPECIALIST_SECTION: dict[str, int] = {
    "integration": 6,
    "agents": 7,
    "reliability": 8,
    "customer_implementation": 9,
}


@lru_cache(maxsize=8)
def read_prompt_file(name: str) -> str:
    path = Path(PROMPTS_DIR) / name
    if not path.exists():
        raise FileNotFoundError(f"prompt file missing: {path}")
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=4)
def parse_sections(name: str = SPECIALIST_DOC) -> dict[int, str]:
    """Split a prompt doc on `# <n>. <title>` headings."""
    text = read_prompt_file(name)
    matches = list(_SECTION_RE.finditer(text))
    sections: dict[int, str] = {}
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[int(match.group(1))] = text[start:end].strip()
    return sections


def compose(section_numbers: tuple[int, ...], doc: str = SPECIALIST_DOC) -> str:
    sections = parse_sections(doc)
    missing = [n for n in section_numbers if n not in sections]
    if missing:
        raise ValueError(f"{doc} is missing expected sections: {missing}")
    return "\n\n---\n\n".join(sections[n] for n in section_numbers)


@lru_cache(maxsize=8)
def specialist_prompt(domain: str) -> str:
    """Shared philosophy + one specialist's own section + continuity rules."""
    if domain not in SPECIALIST_SECTION:
        raise ValueError(f"unknown specialist domain: {domain}")
    numbers = SHARED_SECTIONS + (SPECIALIST_SECTION[domain],) + (11,)
    body = compose(numbers)
    return (
        f"{body}\n\n---\n\n"
        "# Your job on this turn\n\n"
        f"You are the {domain} specialist. You are NOT talking to the interviewer.\n"
        "You are handing dense notes to a final editor who writes what the candidate says.\n\n"
        "Return plain text using these labels, no markdown headers, no preamble:\n\n"
        "ANSWER: the direct answer in one or two sentences.\n"
        "REASONING: the ordered decision path, one step per line.\n"
        "MECHANICS: the specific technical points that are worth saying out loud, "
        "one per line, that are not already in ANSWER.\n"
        "DEEPER: the one layer you would add only if the interviewer pushes.\n"
        "RISKS: anything the candidate must not claim without verifying it.\n\n"
        "Be specific and short. No filler, no restating the question, no closing summary.\n"
        "Never invent provider-specific API behaviour."
    )


@lru_cache(maxsize=1)
def router_prompt() -> str:
    return f"{read_prompt_file(ROUTER_DOC)}\n\n---\n\n{compose(MODE_SECTION)}"


@lru_cache(maxsize=1)
def editor_prompt() -> str:
    body = compose(SHARED_SECTIONS[2:] + CONTINUITY_SECTIONS + EDITOR_CHECKLIST)
    return f"{read_prompt_file(EDITOR_DOC)}\n\n---\n\n{body}"


def clear_cache() -> None:
    """Drop cached prompts so edits to the markdown take effect (dev/tests)."""
    read_prompt_file.cache_clear()
    parse_sections.cache_clear()
    specialist_prompt.cache_clear()
    router_prompt.cache_clear()
    editor_prompt.cache_clear()
