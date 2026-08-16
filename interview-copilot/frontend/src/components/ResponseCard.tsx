import { useState } from "react";
import type { DisplayAnswer } from "../types";

interface Props {
  answer: DisplayAnswer | null;
  error: string | null;
}

function plainText(answer: DisplayAnswer): string {
  const lines = [answer.say, ""];
  if (answer.path.length) lines.push(`PATH: ${answer.path.join(" → ")}`, "");
  if (answer.build.length) lines.push(...answer.build.map((b) => `• ${b}`), "");
  if (answer.push) lines.push(`IF THEY PUSH: ${answer.push}`, "");
  if (answer.next_probe) lines.push(`NEXT: ${answer.next_probe}`);
  return lines.join("\n").trim();
}

export function ResponseCard({ answer, error }: Props) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    if (!answer) return;
    try {
      await navigator.clipboard.writeText(plainText(answer));
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard unavailable over plain http on some devices */
    }
  };

  if (error) {
    return (
      <section className="answer">
        <div className="banner banner-error">{error}</div>
      </section>
    );
  }

  if (!answer) {
    return (
      <section className="answer answer-empty">
        <p className="hint">
          Record or type the interviewer&apos;s question, then press Enter.
        </p>
        <p className="hint hint-dim">
          <kbd>⌘M</kbd> mic · <kbd>Enter</kbd> send · <kbd>Shift+Enter</kbd> newline
        </p>
      </section>
    );
  }

  return (
    <section className="answer">
      <header className="answer-head">
        <div className="badges">
          <span className="badge badge-mode">{answer.mode.replace(/_/g, " ")}</span>
          {answer.turn !== null && <span className="badge">turn {answer.turn}</span>}
          {answer.latency_ms !== null && (
            <span className="badge badge-latency">{(answer.latency_ms / 1000).toFixed(1)}s</span>
          )}
          {answer.streaming && <span className="badge badge-live">writing…</span>}
        </div>
        <button className="ghost" onClick={copy} disabled={answer.streaming}>
          {copied ? "copied" : "copy"}
        </button>
      </header>

      {answer.warning && <div className="banner banner-warn">{answer.warning}</div>}

      <div className="block block-say">
        <h2>SAY</h2>
        <p className="say">{answer.say || "…"}</p>
      </div>

      {answer.path.length > 0 && (
        <div className="block">
          <h2>PATH</h2>
          <p className="path">{answer.path.join("  →  ")}</p>
        </div>
      )}

      {answer.build.length > 0 && (
        <div className="block">
          <h2>BUILD</h2>
          <ul className="build">
            {answer.build.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {answer.push && (
        <div className="block">
          <h2>IF THEY PUSH</h2>
          <p className="push">{answer.push}</p>
        </div>
      )}

      {answer.next_probe && (
        <div className="block block-next">
          <h2>NEXT</h2>
          <p className="next">{answer.next_probe}</p>
        </div>
      )}
    </section>
  );
}
