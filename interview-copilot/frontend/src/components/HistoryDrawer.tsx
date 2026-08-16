import type { TurnSummary } from "../types";

interface Props {
  turns: TurnSummary[];
  open: boolean;
  onToggle: () => void;
  onSelect: (turn: TurnSummary) => void;
  activeTurn: number | null;
}

export function HistoryDrawer({ turns, open, onToggle, onSelect, activeTurn }: Props) {
  return (
    <aside className={`history ${open ? "history-open" : ""}`}>
      <button className="history-toggle" onClick={onToggle} type="button">
        {open ? "×" : `history${turns.length ? ` (${turns.length})` : ""}`}
      </button>

      {open && (
        <div className="history-body">
          {turns.length === 0 && <p className="hint hint-dim">No turns yet.</p>}
          {[...turns].reverse().map((turn) => (
            <button
              key={turn.turn}
              type="button"
              className={`history-item ${activeTurn === turn.turn ? "history-item-active" : ""}`}
              onClick={() => onSelect(turn)}
            >
              <span className="history-meta">
                <span className="history-turn">#{turn.turn}</span>
                <span className="history-mode">{turn.mode.replace(/_/g, " ")}</span>
              </span>
              <span className="history-q">{turn.interviewer_text}</span>
              <span className="history-a">{turn.say}</span>
            </button>
          ))}
        </div>
      )}
    </aside>
  );
}
