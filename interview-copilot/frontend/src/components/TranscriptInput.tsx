import { forwardRef } from "react";
import type { RecorderState } from "../hooks/useRecorder";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onToggleMic: () => void;
  recorderState: RecorderState;
  busy: boolean;
  notice: string | null;
}

const MIC_LABEL: Record<RecorderState, string> = {
  idle: "Start recording (⌘M)",
  recording: "Stop recording (⌘M)",
  transcribing: "Transcribing…",
  denied: "Microphone blocked — type instead",
};

export const TranscriptInput = forwardRef<HTMLTextAreaElement, Props>(function TranscriptInput(
  { value, onChange, onSubmit, onToggleMic, recorderState, busy, notice },
  ref,
) {
  return (
    <div className="composer">
      {notice && <div className="banner banner-warn composer-notice">{notice}</div>}
      <div className="composer-row">
        <button
          type="button"
          className={`mic mic-${recorderState}`}
          onClick={onToggleMic}
          disabled={recorderState === "transcribing"}
          aria-label={MIC_LABEL[recorderState]}
          title={MIC_LABEL[recorderState]}
        >
          <span className="mic-dot" />
          {recorderState === "recording"
            ? "listening"
            : recorderState === "transcribing"
              ? "…"
              : "mic"}
        </button>

        <textarea
          ref={ref}
          className="transcript"
          value={value}
          placeholder="Interviewer question — record it, or type it."
          rows={2}
          spellCheck={false}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              onSubmit();
            }
          }}
        />

        <button
          type="button"
          className="send"
          onClick={onSubmit}
          disabled={busy || !value.trim()}
        >
          {busy ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
});
