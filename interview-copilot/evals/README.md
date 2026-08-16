# Evals

A regression net for prompt changes. Every check is deterministic Python over
the real pipeline output — there is no LLM grading the LLM.

## Run

```bash
# validate the case files, no API calls, no key needed
backend/.venv/bin/python evals/run_evals.py --dry-run

# the real thing (needs OPENAI_API_KEY in .env)
backend/.venv/bin/python evals/run_evals.py

backend/.venv/bin/python evals/run_evals.py --cases-only
backend/.venv/bin/python evals/run_evals.py --filter incident
backend/.venv/bin/python evals/run_evals.py --json eval-report.json --verbose
```

Cases run in-process against `Orchestrator` — no server required. Concurrency
defaults to 3; raise it with `--concurrency` if your rate limits allow.

Exit code is 0 when everything passes, 1 on failures, 2 on a bad case file or
missing key.

## What is in here

- `cases.json` — 32 single-turn cases
- `sequences.json` — 9 multi-turn sequences (27 turns)

Categories covered: OAuth expiry, refresh-token revocation, webhook duplicates
and signatures, idempotency, timeout-after-write, 429s, a hard RPS ceiling, a
five-minute production incident, booking races, provider 500s, customers with no
API, multiple systems of record, discovery, wrong-tool debugging, invented IDs,
prompt injection, RAG failure, agent state continuity, screen-share
walkthroughs, framework judgement, and interviewer pushback.

## Assertion vocabulary

Per case, under `expect`:

| key | meaning |
| --- | --- |
| `must_include_any` | list of synonym groups; **each group** needs at least one hit |
| `must_not_include` | none of these may appear — this is where the traps live |
| `modes` | allowed values for the detected mode |
| `domains` | allowed primary domain |
| `budget` | exact `response_budget` the router must choose |
| `max_words` / `min_words` | word count across SAY + PATH + BUILD + PUSH |
| `is_followup` | router must have flagged the turn as a follow-up |
| `changes_prior_assumption` | router must have noticed the new constraint |
| `state_contains` | substrings that must survive into `InterviewState` |
| `no_restart` | the opening must not be a near-copy of turn 1's opening |

Every case also asserts **no cross-section repetition**: if the deterministic
quality gate had to strip a duplicate, that is a prompt regression and the case
fails.

Assertions are lexical and synonym-tolerant on purpose. They catch "the answer
lost the point" and "the answer walked into the trap" — they do not grade prose.

## The two that matter most

**`five_minute_incident`** must inspect what is consuming quota, stop retry
amplification and non-critical traffic, and protect live auth. It must *not*
propose Kafka, claim a queue creates capacity, or launch into a redesign.

**`booking_timeout_escalation`** stacks three constraints across three turns.
By turn 3 the state must still hold all of them, the answer must say explicitly
that the earlier recommendation no longer works, and the opening must not
restart the scenario.

## When a case fails

Look at the failing check name first — it says which group of terms was missing
or which trap was hit. Then run with `--verbose` to see the actual answer, and
tune `backend/app/prompts/editor.md` or the relevant specialist section in
`specialist-agents.md`. Re-run with `--filter <id>` to iterate on one case.

Some drift is normal across model versions. Fix the prompt, not the assertion —
unless the assertion was genuinely too narrow.
