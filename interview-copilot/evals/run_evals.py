#!/usr/bin/env python3
"""Eval harness for the interview copilot.

Runs the real pipeline in-process (no server needed) and checks deterministic
properties of the answer: did it cover the point, did it avoid the trap, did it
stay inside its budget, did the state carry forward, did a follow-up evolve the
recommendation instead of restarting.

    python evals/run_evals.py --dry-run           # validate cases, no API calls
    python evals/run_evals.py                     # everything (needs a key)
    python evals/run_evals.py --cases-only
    python evals/run_evals.py --filter incident
    python evals/run_evals.py --json report.json

Assertions are intentionally lexical and synonym-tolerant. They are a
regression net for prompt changes, not a grader of prose quality.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EVALS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = EVALS_DIR.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.models.api import MessageResponse  # noqa: E402
from app.persistence.sqlite import SQLiteSessionStore  # noqa: E402
from app.services.orchestrator import Orchestrator  # noqa: E402
from app.services.quality import similarity, word_count  # noqa: E402

RESTART_SIMILARITY = 0.6

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class CaseResult:
    case_id: str
    category: str
    checks: list[CheckResult] = field(default_factory=list)
    latency_ms: int = 0
    mode: str = ""
    error: str | None = None
    answer: dict[str, Any] | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(check.passed for check in self.checks)


# --------------------------------------------------------------------- checks


def answer_text(response: MessageResponse) -> str:
    parts = [response.say, " ".join(response.path), " ".join(response.build)]
    if response.push:
        parts.append(response.push)
    if response.next_probe:
        parts.append(response.next_probe)
    return " ".join(parts).lower()


def as_response_model(response: MessageResponse):
    from app.models.interview import InterviewResponse

    return InterviewResponse(
        say=response.say,
        path=response.path,
        build=response.build,
        push=response.push,
        next_probe=response.next_probe,
        response_mode=response.mode,
        answer_summary=response.answer_summary,
    )


def check_case(
    response: MessageResponse,
    expect: dict[str, Any],
    *,
    first_say: str | None = None,
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    body = answer_text(response)
    debug = response.debug
    routing: dict[str, Any] = dict(debug.routing) if debug else {}

    for group in expect.get("must_include_any", []):
        hit = next((term for term in group if term.lower() in body), None)
        checks.append(
            CheckResult(
                name=f"mentions one of {group[:3]}{'…' if len(group) > 3 else ''}",
                passed=hit is not None,
                detail="" if hit else "none of these appeared",
            )
        )

    for term in expect.get("must_not_include", []):
        present = term.lower() in body
        checks.append(
            CheckResult(
                name=f"avoids {term!r}",
                passed=not present,
                detail=f"found {term!r}" if present else "",
            )
        )

    if "modes" in expect:
        allowed = expect["modes"]
        checks.append(
            CheckResult(
                name="mode is plausible",
                passed=response.mode in allowed,
                detail=f"got {response.mode}, expected one of {allowed}",
            )
        )

    if "domains" in expect and debug and debug.domains:
        primary = debug.domains[0]
        checks.append(
            CheckResult(
                name="primary domain is plausible",
                passed=primary in expect["domains"],
                detail=f"got {primary}, expected one of {expect['domains']}",
            )
        )

    if "budget" in expect and routing:
        got = routing.get("response_budget")
        checks.append(
            CheckResult(
                name=f"budget is {expect['budget']}",
                passed=got == expect["budget"],
                detail=f"got {got}",
            )
        )

    words = word_count(as_response_model(response))
    if "max_words" in expect:
        checks.append(
            CheckResult(
                name=f"under {expect['max_words']} words",
                passed=words <= expect["max_words"],
                detail=f"{words} words",
            )
        )
    if "min_words" in expect:
        checks.append(
            CheckResult(
                name=f"at least {expect['min_words']} words",
                passed=words >= expect["min_words"],
                detail=f"{words} words",
            )
        )

    if expect.get("is_followup"):
        got = bool(routing.get("is_followup"))
        checks.append(CheckResult(name="classified as follow-up", passed=got))

    if expect.get("changes_prior_assumption"):
        got = bool(routing.get("changes_prior_assumption"))
        checks.append(CheckResult(name="noticed the changed constraint", passed=got))

    if "state_contains" in expect and debug:
        blob = json.dumps(debug.state).lower()
        for term in expect["state_contains"]:
            checks.append(
                CheckResult(
                    name=f"state remembers {term!r}",
                    passed=term.lower() in blob,
                    detail="" if term.lower() in blob else "missing from state",
                )
            )

    if expect.get("no_restart") and first_say:
        score = similarity(response.say, first_say)
        checks.append(
            CheckResult(
                name="does not restart the scenario",
                passed=score < RESTART_SIMILARITY,
                detail=f"similarity to turn 1 opening was {score:.2f}",
            )
        )

    # Anti-repetition is enforced in code; if the gate had to strip anything the
    # editor prompt is drifting and that is worth seeing in the report.
    if debug:
        dropped = [note for note in debug.quality_notes if note.startswith("dropped")]
        checks.append(
            CheckResult(
                name="no cross-section repetition",
                passed=not dropped,
                detail="; ".join(dropped),
            )
        )

    return checks


# ----------------------------------------------------------------- execution


async def run_case(orchestrator: Orchestrator, case: dict[str, Any]) -> CaseResult:
    result = CaseResult(case_id=case["id"], category=case.get("category", "uncategorised"))
    session = await orchestrator.create_session()
    started = time.perf_counter()
    try:
        response = await orchestrator.handle_message(session.session_id, case["prompt"])
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    result.latency_ms = int((time.perf_counter() - started) * 1000)
    result.mode = response.mode
    result.checks = check_case(response, case.get("expect", {}))
    result.answer = {"say": response.say, "path": response.path, "build": response.build}
    return result


async def run_sequence(orchestrator: Orchestrator, sequence: dict[str, Any]) -> CaseResult:
    result = CaseResult(
        case_id=sequence["id"], category=sequence.get("category", "sequence")
    )
    session = await orchestrator.create_session()
    first_say: str | None = None
    started = time.perf_counter()

    for index, turn in enumerate(sequence["turns"], start=1):
        try:
            response = await orchestrator.handle_message(session.session_id, turn["prompt"])
        except Exception as exc:  # noqa: BLE001
            result.error = f"turn {index}: {type(exc).__name__}: {exc}"
            return result

        if first_say is None:
            first_say = response.say
        result.mode = response.mode
        for check in check_case(response, turn.get("expect", {}), first_say=first_say):
            check.name = f"t{index}: {check.name}"
            result.checks.append(check)
        result.answer = {"final_say": response.say}

    result.latency_ms = int((time.perf_counter() - started) * 1000)
    return result


# -------------------------------------------------------------------- report


def validate(cases: list[dict], sequences: list[dict]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()

    for case in cases:
        if "id" not in case or "prompt" not in case:
            problems.append(f"case missing id/prompt: {case}")
            continue
        if case["id"] in seen:
            problems.append(f"duplicate id: {case['id']}")
        seen.add(case["id"])
        for group in case.get("expect", {}).get("must_include_any", []):
            if not isinstance(group, list) or not group:
                problems.append(f"{case['id']}: must_include_any needs non-empty groups")

    for sequence in sequences:
        if not sequence.get("turns"):
            problems.append(f"sequence {sequence.get('id')} has no turns")
        if sequence.get("id") in seen:
            problems.append(f"duplicate id: {sequence.get('id')}")
        seen.add(sequence.get("id", ""))

    return problems


def print_result(result: CaseResult, verbose: bool) -> None:
    failed = [c for c in result.checks if not c.passed]
    if result.error:
        print(f"{RED}ERROR{RESET} {result.case_id}  {result.error}")
        return

    status = f"{GREEN}PASS{RESET}" if result.passed else f"{RED}FAIL{RESET}"
    print(
        f"{status} {result.case_id:<32} {DIM}{result.mode:<24}"
        f"{len(result.checks) - len(failed)}/{len(result.checks)} checks"
        f"  {result.latency_ms}ms{RESET}"
    )
    for check in failed:
        print(f"       {RED}·{RESET} {check.name}{f' — {check.detail}' if check.detail else ''}")
    if verbose and result.answer:
        for key, value in result.answer.items():
            print(f"       {DIM}{key}: {value}{RESET}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate case files only")
    parser.add_argument("--cases-only", action="store_true")
    parser.add_argument("--sequences-only", action="store_true")
    parser.add_argument("--filter", default="", help="substring match on id or category")
    parser.add_argument("--json", dest="json_out", default="", help="write a JSON report")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--concurrency", type=int, default=3, help="parallel cases (keep low to avoid rate limits)"
    )
    args = parser.parse_args()

    cases = json.loads((EVALS_DIR / "cases.json").read_text())
    sequences = json.loads((EVALS_DIR / "sequences.json").read_text())

    problems = validate(cases, sequences)
    if problems:
        print(f"{RED}case files are invalid:{RESET}")
        for problem in problems:
            print(f"  · {problem}")
        return 2

    if args.filter:
        needle = args.filter.lower()
        cases = [c for c in cases if needle in c["id"].lower() or needle in c.get("category", "")]
        sequences = [
            s for s in sequences if needle in s["id"].lower() or needle in s.get("category", "")
        ]

    if args.sequences_only:
        cases = []
    if args.cases_only:
        sequences = []

    if args.dry_run:
        categories: dict[str, int] = {}
        for item in cases + sequences:
            categories[item.get("category", "?")] = categories.get(item.get("category", "?"), 0) + 1
        print(f"{GREEN}case files are valid{RESET}")
        print(f"  {len(cases)} single-turn cases")
        print(f"  {len(sequences)} multi-turn sequences")
        print(f"  {sum(len(s['turns']) for s in sequences)} sequence turns")
        print("  coverage:")
        for name, count in sorted(categories.items()):
            print(f"    {name:<20} {count}")
        return 0

    settings = get_settings()
    if not settings.openai_api_key:
        print(f"{RED}OPENAI_API_KEY is not set — use --dry-run to validate offline.{RESET}")
        return 2

    print(
        f"{DIM}router={settings.router_model} specialist={settings.specialist_model} "
        f"editor={settings.editor_model} deep={settings.deep_model}{RESET}\n"
    )

    store = SQLiteSessionStore(":memory:")
    await store.init()
    orchestrator = Orchestrator(store)
    semaphore = asyncio.Semaphore(max(1, args.concurrency))

    async def guarded(coro_factory):
        async with semaphore:
            return await coro_factory()

    started = time.perf_counter()
    results: list[CaseResult] = []

    if cases:
        print(f"{YELLOW}single-turn cases{RESET}")
        gathered = await asyncio.gather(
            *[guarded(lambda c=c: run_case(orchestrator, c)) for c in cases]
        )
        for result in gathered:
            print_result(result, args.verbose)
            results.append(result)

    if sequences:
        print(f"\n{YELLOW}multi-turn sequences{RESET}")
        gathered = await asyncio.gather(
            *[guarded(lambda s=s: run_sequence(orchestrator, s)) for s in sequences]
        )
        for result in gathered:
            print_result(result, args.verbose)
            results.append(result)

    await store.close()

    passed = sum(1 for r in results if r.passed)
    total_checks = sum(len(r.checks) for r in results)
    failed_checks = sum(1 for r in results for c in r.checks if not c.passed)
    elapsed = time.perf_counter() - started

    print(
        f"\n{GREEN if passed == len(results) else RED}{passed}/{len(results)} passed{RESET}"
        f"  ({total_checks - failed_checks}/{total_checks} checks, {elapsed:.1f}s)"
    )

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(
                [
                    {
                        "id": r.case_id,
                        "category": r.category,
                        "passed": r.passed,
                        "mode": r.mode,
                        "latency_ms": r.latency_ms,
                        "error": r.error,
                        "failed_checks": [
                            {"name": c.name, "detail": c.detail} for c in r.checks if not c.passed
                        ],
                        "answer": r.answer,
                    }
                    for r in results
                ],
                indent=2,
            )
        )
        print(f"{DIM}report written to {args.json_out}{RESET}")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
