import { useState } from "react";
import type { DebugInfo } from "../types";

interface Props {
  debug: DebugInfo | null;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="debug-row">
      <span className="debug-key">{label}</span>
      <span className="debug-val">{value}</span>
    </div>
  );
}

function Json({ label, value }: { label: string; value: unknown }) {
  return (
    <details className="debug-json">
      <summary>{label}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

/** Collapsed by default — this is for tuning before the interview, not during. */
export function DebugDrawer({ debug }: Props) {
  const [open, setOpen] = useState(false);

  if (!debug) return null;
  const t = debug.timings;

  return (
    <section className={`debug ${open ? "debug-open" : ""}`}>
      <button className="debug-toggle" onClick={() => setOpen(!open)} type="button">
        {open ? "▾" : "▸"} debug
        <span className="debug-summary">
          {debug.mode} · {debug.specialists.join(" + ") || "none"} · {t.total_latency_ms}ms
          {debug.fallback_used.length > 0 && " · fallback"}
          {!debug.persistence_ok && " · not saved"}
        </span>
      </button>

      {open && (
        <div className="debug-body">
          <Row label="request" value={debug.request_id} />
          <Row label="mode" value={debug.mode} />
          <Row label="domains" value={debug.domains.join(", ")} />
          <Row label="specialists" value={debug.specialists.join(", ") || "none"} />
          <Row
            label="models"
            value={`router ${debug.router_model} · specialist ${debug.specialist_model} · editor ${debug.editor_model}`}
          />
          <Row
            label="latency"
            value={`router ${t.router_latency_ms}ms · specialist ${t.specialist_latency_ms}ms · editor ${t.editor_latency_ms}ms · total ${t.total_latency_ms}ms`}
          />
          <Row label="router skipped" value={debug.router_skipped ? "yes (chip)" : "no"} />
          <Row label="persisted" value={debug.persistence_ok ? "yes" : "NO"} />

          {debug.fallback_used.length > 0 && (
            <div className="debug-alert">
              {debug.fallback_used.map((note, index) => (
                <div key={index}>fallback: {note}</div>
              ))}
            </div>
          )}
          {debug.quality_notes.length > 0 && (
            <div className="debug-notes">
              {debug.quality_notes.map((note, index) => (
                <div key={index}>quality: {note}</div>
              ))}
            </div>
          )}

          <Json label="routing decision" value={debug.routing} />
          <Json label="interview state" value={debug.state} />
          <Json label="state delta" value={debug.state_delta} />
          {Object.keys(debug.specialist_output).length > 0 && (
            <Json label="raw specialist output" value={debug.specialist_output} />
          )}
        </div>
      )}
    </section>
  );
}
