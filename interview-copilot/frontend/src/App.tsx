import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./api";
import { CommandChips } from "./components/CommandChips";
import { DebugDrawer } from "./components/DebugDrawer";
import { HistoryDrawer } from "./components/HistoryDrawer";
import { ResponseCard } from "./components/ResponseCard";
import { TranscriptInput } from "./components/TranscriptInput";
import { useRecorder } from "./hooks/useRecorder";
import type { DebugInfo, DisplayAnswer, TurnSummary } from "./types";

const SESSION_KEY = "interview-copilot.session";

function emptyAnswer(mode = "…"): DisplayAnswer {
  return {
    turn: null,
    say: "",
    path: [],
    build: [],
    push: null,
    next_probe: null,
    mode,
    latency_ms: null,
    warning: null,
    streaming: true,
  };
}

function toDisplay(turn: TurnSummary): DisplayAnswer {
  return {
    turn: turn.turn,
    say: turn.say,
    path: turn.path,
    build: turn.build,
    push: turn.push,
    next_probe: turn.next_probe,
    mode: turn.mode,
    latency_ms: turn.latency_ms,
    warning: null,
    streaming: false,
  };
}

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [text, setText] = useState("");
  const [answer, setAnswer] = useState<DisplayAnswer | null>(null);
  const [debug, setDebug] = useState<DebugInfo | null>(null);
  const [turns, setTurns] = useState<TurnSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const flash = useCallback((message: string) => {
    setNotice(message);
    setTimeout(() => setNotice(null), 5000);
  }, []);

  // --- transcription: fills the textarea, never auto-submits ---------------
  const onTranscript = useCallback((transcribed: string) => {
    setText((current) => (current.trim() ? `${current.trim()} ${transcribed}` : transcribed));
    textareaRef.current?.focus();
  }, []);

  const recorder = useRecorder(onTranscript, flash);

  // --- session bootstrap ---------------------------------------------------
  const startSession = useCallback(async () => {
    const { session_id } = await api.createSession();
    localStorage.setItem(SESSION_KEY, session_id);
    setSessionId(session_id);
    setTurns([]);
    setAnswer(null);
    setDebug(null);
    setText("");
    return session_id;
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await api.health();
        if (!cancelled) setConnected(true);
      } catch {
        if (!cancelled) setConnected(false);
      }

      const saved = localStorage.getItem(SESSION_KEY);
      if (saved) {
        try {
          const detail = await api.getSession(saved);
          if (cancelled) return;
          setSessionId(saved);
          setTurns(detail.turns);
          const last = detail.turns[detail.turns.length - 1];
          if (last) setAnswer(toDisplay(last));
          return;
        } catch {
          /* stale session id — fall through and make a new one */
        }
      }
      try {
        if (!cancelled) await startSession();
      } catch {
        if (!cancelled) setError("Cannot reach the backend. Is uvicorn running?");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [startSession]);

  // --- submit --------------------------------------------------------------
  const submit = useCallback(
    async (raw: string) => {
      const question = raw.trim();
      if (!question || busy) return;

      let id = sessionId;
      if (!id) {
        try {
          id = await startSession();
        } catch {
          setError("Cannot reach the backend.");
          return;
        }
      }

      setBusy(true);
      setError(null);
      setText("");
      setAnswer(emptyAnswer());
      setDebug(null);

      const finish = (payload: Parameters<typeof setAnswer>[0]) => setAnswer(payload);

      try {
        await api.streamMessage(id, question, (event) => {
          switch (event.type) {
            case "routing":
              finish((current) => ({ ...(current ?? emptyAnswer()), mode: event.mode }));
              break;
            case "say":
              finish((current) => ({ ...(current ?? emptyAnswer()), say: event.text }));
              break;
            case "final": {
              const p = event.payload;
              finish({
                turn: p.turn,
                say: p.say,
                path: p.path,
                build: p.build,
                push: p.push,
                next_probe: p.next_probe,
                mode: p.mode,
                latency_ms: p.latency_ms,
                warning: p.warning,
                streaming: false,
              });
              setDebug(p.debug);
              setTurns((current) => [
                ...current,
                {
                  turn: p.turn,
                  interviewer_text: question,
                  say: p.say,
                  path: p.path,
                  build: p.build,
                  push: p.push,
                  next_probe: p.next_probe,
                  mode: p.mode,
                  latency_ms: p.latency_ms,
                  created_at: new Date().toISOString(),
                },
              ]);
              break;
            }
            case "error":
              setError(event.message);
              setAnswer(null);
              break;
          }
        });
      } catch {
        // Streaming unavailable — fall back to the plain JSON endpoint rather
        // than losing the turn.
        try {
          const p = await api.sendMessage(id, question);
          finish({
            turn: p.turn,
            say: p.say,
            path: p.path,
            build: p.build,
            push: p.push,
            next_probe: p.next_probe,
            mode: p.mode,
            latency_ms: p.latency_ms,
            warning: p.warning,
            streaming: false,
          });
          setDebug(p.debug);
          setTurns((current) => [
            ...current,
            {
              turn: p.turn,
              interviewer_text: question,
              say: p.say,
              path: p.path,
              build: p.build,
              push: p.push,
              next_probe: p.next_probe,
              mode: p.mode,
              latency_ms: p.latency_ms,
              created_at: new Date().toISOString(),
            },
          ]);
        } catch (fallbackError) {
          setAnswer(null);
          setError(
            fallbackError instanceof Error ? fallbackError.message : "The turn failed.",
          );
          setText(question); // never lose what the candidate typed
        }
      } finally {
        setBusy(false);
        textareaRef.current?.focus();
      }
    },
    [busy, sessionId, startSession],
  );

  // --- keyboard ------------------------------------------------------------
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "m") {
        event.preventDefault();
        recorder.toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [recorder]);

  return (
    <div className="app">
      <header className="topbar">
        <h1>Interview Copilot</h1>
        <div className="topbar-right">
          <button className="ghost" onClick={() => void startSession()} type="button">
            new interview
          </button>
          <span className={`status ${connected ? "status-ok" : "status-down"}`}>
            <span className="status-dot" />
            {connected ? "connected" : "offline"}
          </span>
        </div>
      </header>

      <main className="main">
        <ResponseCard answer={answer} error={error} />
      </main>

      <footer className="footer">
        <DebugDrawer debug={debug} />
        <CommandChips onSelect={(chip) => void submit(chip)} disabled={busy || !sessionId} />
        <TranscriptInput
          ref={textareaRef}
          value={text}
          onChange={setText}
          onSubmit={() => void submit(text)}
          onToggleMic={recorder.toggle}
          recorderState={recorder.state}
          busy={busy}
          notice={notice}
        />
      </footer>

      <HistoryDrawer
        turns={turns}
        open={historyOpen}
        onToggle={() => setHistoryOpen((open) => !open)}
        onSelect={(turn) => {
          setAnswer(toDisplay(turn));
          setHistoryOpen(false);
        }}
        activeTurn={answer?.turn ?? null}
      />
    </div>
  );
}
