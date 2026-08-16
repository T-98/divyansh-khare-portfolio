# Interview Copilot

A live technical-interview copilot for integrations, AI-agent, debugging and
customer-implementation questions. You hear the interviewer, record the
question, hit Send, and the first line you can say out loud appears while the
rest of the answer is still being written.

It is not a chatbot and not a textbook. It behaves like a staff-level
integrations engineer sitting next to you: a spoken opening, the reasoning path,
the mechanics, one deeper layer held in reserve, and the probe that is coming
next.

```
┌───────────────────────────────────────────────────────┐
│ Interview Copilot                         ● connected │
├───────────────────────────────────────────────────────┤
│ SAY                                                   │
│ I'd treat that as an unknown outcome, not a failure.  │
│                                                       │
│ PATH                                                  │
│ timeout → reconcile → safe retry                      │
│                                                       │
│ BUILD                                                 │
│ • Check whether their API supports an idempotency key │
│ • Look the operation up before writing again          │
│                                                       │
│ IF THEY PUSH  …          NEXT → …                     │
├───────────────────────────────────────────────────────┤
│ 🎙 listening   interviewer transcript…        [Send]  │
└───────────────────────────────────────────────────────┘
```

---

## Quick start

```bash
cp .env.example .env      # then add OPENAI_API_KEY
./run.sh                  # installs on first run, then starts both servers
```

Open <http://localhost:5173>. That is it.

Manual equivalent:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# second terminal
cd frontend && npm install && npm run dev
```

### Using it from a second device

`run.sh` binds both servers to `0.0.0.0`, so open
`http://<your-laptop-ip>:5173` from a phone or tablet on the same network.

One catch: **browsers only allow microphone access on `localhost` or HTTPS.**
On a second device over plain HTTP the mic button will be blocked and you will
have to type. Either run the copilot on the device you are reading from, or put
a TLS tunnel in front of it. Everything else works over LAN unchanged.

---

## How a turn works

```
transcribe → router → specialist(s) → editor → quality gate → render
```

Three model calls on the default path. The router is fast and cheap and never
writes candidate-facing text. One specialist answers; a second runs concurrently
via `asyncio.gather` only when the question genuinely mixes domains. The editor
is the only agent whose words you ever see.

**Streaming is why the first line is fast.** Three sequential calls cannot put
text on screen in two seconds, so the editor's structured output is streamed and
`say` is declared first in the schema — it is parsed out of the partial JSON
buffer and rendered the moment it arrives, while `build` and `push` are still
generating. The blocking `POST …/messages` endpoint is still the documented
contract and is what the evals use; the UI uses `POST …/messages/stream` and
falls back to the blocking one automatically.

**Chips skip the router entirely.** `deeper`, `debug`, `screen` and friends are
classified in Python (`agents/router.py`), which removes a whole network round
trip on exactly the turns where you are already mid-sentence.

### Specialists

Four, from `prompts/specialist-agents.md`: integration, agents, reliability, and
customer implementation. Routing rules — incidents go to reliability,
screen-share walkthroughs pair integration with customer implementation, deep
agent questions go to agents. Never more than two, enforced in code rather than
trusted to the router.

### State

Raw history alone loses the constraints an interviewer stacks up. `InterviewState`
carries them explicitly:

```
turn 1  booking POST timed out
turn 2  provider has no idempotency support
turn 3  provider cannot be queried afterwards
```

By turn 3 all three constraints are in state, the router flags
`changes_prior_assumption`, and the editor is required to say what no longer
holds before giving the revised move — not to restart the scenario.

State advances from the editor's structured `state_delta` merged deterministically
in `services/state.py`. No extra model call is spent on bookkeeping.

### The quality gate

Anti-repetition runs in Python on every turn (`services/quality.py`), not as
another model call. Section ownership is enforced by token-overlap similarity: a
BUILD bullet that restates SAY is dropped, an IF-THEY-PUSH that only paraphrases
earlier text is removed entirely. Budget and sub-question coverage produce
advisory notes in the debug drawer rather than blocking the answer.

---

## Keyboard and controls

| Key | Action |
| --- | --- |
| `Cmd/Ctrl + M` | toggle microphone |
| `Enter` | send |
| `Shift + Enter` | newline |

Transcription fills the textarea and **never auto-submits** — you always edit
before sending. If transcription fails, whatever you typed is preserved and an
error appears under the composer.

Chips (`deeper`, `technical`, `why`, `failure`, `debug`, `scale`, `security`,
`screen`, `push`) submit that word as a follow-up in the same session.

---

## API

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/api/sessions` | new session |
| `GET` | `/api/sessions/{id}` | turns + current state |
| `DELETE` | `/api/sessions/{id}` | |
| `POST` | `/api/sessions/{id}/messages` | blocking turn, full JSON |
| `POST` | `/api/sessions/{id}/messages/stream` | SSE: `routing` → `say` → `final` |
| `POST` | `/api/transcribe` | multipart audio → text |
| `GET` | `/health` | configured models, key present, db path |

```json
{
  "session_id": "…", "turn": 4,
  "say": "…",
  "path": ["unknown outcome", "check idempotency", "reconcile", "retry only if safe"],
  "build": ["…"],
  "push": "…", "next_probe": "…",
  "mode": "scenario", "latency_ms": 1380
}
```

Optional fields come back as `null` and are hidden in the UI. `debug` carries
the drawer payload.

---

## Models

All configurable, none hard-coded:

```env
ROUTER_MODEL=gpt-5.6-luna        # fast, structured output only
SPECIALIST_MODEL=gpt-5.6-terra   # balanced reasoning
EDITOR_MODEL=gpt-5.6-terra       # same by default
DEEP_MODEL=gpt-5.6-sol           # strongest — see below
TRANSCRIBE_MODEL=gpt-4o-transcribe
FALLBACK_MODEL=gpt-4.1
```

**The deep model is not used every turn.** It runs only when the router says
`complexity: deep` *and* a single specialist is handling the turn — paying for
the strongest model twice in parallel is how a live answer arrives too late to
be useful.

**If a model ID does not exist on your account**, the call is retried once on
`FALLBACK_MODEL`, the substitution is logged, and the debug drawer shows
`fallback`. That keeps the app usable on any account, but you should set the
right IDs in `.env` for predictable latency. Verify before the interview:

```bash
LIVE_TESTS=1 backend/.venv/bin/python -m pytest -m live -s
```

That test fails if any configured model had to fall back.

---

## Debug drawer

Collapsed by default, under the chips. Shows detected mode, domains, selected
specialists, all three model names, per-stage and total latency, the full routing
decision, the current `InterviewState`, this turn's `state_delta`, quality-gate
notes, whether the router was skipped, whether persistence succeeded, and any
fallbacks. Set `DEBUG_AGENT_OUTPUT=true` to include raw specialist notes.

This is for tuning before the interview, not for reading during one.

---

## Tests and evals

```bash
cd backend && .venv/bin/python -m pytest          # 132 tests, offline, ~1s
LIVE_TESTS=1 .venv/bin/python -m pytest -m live   # real models, opt-in

backend/.venv/bin/python evals/run_evals.py --dry-run   # validate cases offline
backend/.venv/bin/python evals/run_evals.py             # 32 cases + 9 sequences
```

OpenAI is mocked everywhere except the `live` marker. See `evals/README.md` for
the assertion vocabulary and what the incident and multi-turn cases require.

---

## Failure behaviour

Nothing on screen while the interviewer waits is the worst outcome, so every
stage degrades instead of failing:

- **router fails** → keyword fallback classifier, turn continues
- **one specialist fails** → the editor answers from state and the survivor
- **editor fails** → one direct call on the specialist model
- **that fails too** → the answer is assembled from specialist notes in Python,
  no model call at all
- **persistence fails** → the answer is still delivered, with a visible warning
  that follow-ups may lose earlier constraints. Continuity is never silently
  faked.
- **transcription fails** → your typed text is untouched, error shown, type and
  send normally

Retries are deliberately single-attempt. Stacking retries in front of someone
mid-sentence is worse than degrading fast.

---

## Privacy and security

- The OpenAI key is backend-only and never reaches the browser.
- Raw audio is never persisted. The temp file is deleted in a `finally`,
  including on failure — there is a test that asserts this.
- Structured logs redact anything key-shaped.
- Sessions and transcripts are stored in local SQLite. `interview.db` is
  gitignored; delete it to wipe history.

---

## Layout

```
backend/app/
  agents/      router · specialists · editor · llm · prompt_loader
  services/    orchestrator · state · quality · transcription · partial_json
  persistence/ base (interface) · sqlite
  prompts/     specialist-agents.md · router.md · editor.md
frontend/src/  App · components · hooks/useRecorder · api · types
evals/         cases.json · sequences.json · run_evals.py
```

`prompts/specialist-agents.md` is the behavioural source of truth. It is parsed
into its numbered sections and each agent is composed from only the sections it
needs — the integration specialist never sees the agents specialist's section,
which keeps prompts small and latency down. Editing the markdown changes
behaviour with no code change; `clear_cache()` drops the cached slices.

---

## Design decisions worth knowing

**No OpenAI Agents SDK.** The runtime is three calls with hand-written fan-out.
A session/handoff framework would add a dependency and latency without removing
any code. Structured output goes through Chat Completions with a strict
`json_schema` and Pydantic validation, which is the most portable path across
SDK versions and keeps the streaming and blocking cases on identical code.

**`state_delta` is typed, not a free-form dict.** The spec sketches it as
`dict`, but strict structured output cannot express an open object, and a typed
delta makes the merge unit-testable. It is serialised as a plain dict on the
wire, so the documented API shape is unchanged.

**SQLite with one connection behind a lock.** A live interview is one person on
one laptop. `persistence/base.py` is the interface; swapping in Postgres touches
one file.

**No Kafka, Redis, Celery, Temporal, or a vector database.** None of them have a
requirement here. The app is also opinionated that *you* should not reach for
them reflexively in the interview — the editor prompt enforces failure-class
before technology, and the evals fail any answer that claims a queue creates
capacity.

## Known MVP limitations

- Transcription is batch (record → stop → upload), not Realtime. It sits behind
  the `Transcriber` interface so a WebSocket implementation can replace it
  without touching the API or the UI.
- Microphone needs `localhost` or HTTPS — see the second-device note above.
- No auth on the API. It is a local single-user tool; do not expose it publicly.
- Session history lives in one SQLite file with no migrations.
- The quality gate is lexical. It reliably catches restatement; it will not
  catch two sentences that make the same point in entirely different words.
- Eval assertions are lexical too, and will need occasional widening as models
  change their phrasing.
