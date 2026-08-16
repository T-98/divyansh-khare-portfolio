export interface TimingBreakdown {
  router_latency_ms: number;
  specialist_latency_ms: number;
  editor_latency_ms: number;
  total_latency_ms: number;
}

export interface DebugInfo {
  request_id: string;
  mode: string;
  domains: string[];
  specialists: string[];
  router_model: string;
  specialist_model: string;
  editor_model: string;
  timings: TimingBreakdown;
  routing: Record<string, unknown>;
  state: Record<string, unknown>;
  state_delta: Record<string, unknown>;
  specialist_output: Record<string, string>;
  fallback_used: string[];
  quality_notes: string[];
  router_skipped: boolean;
  persistence_ok: boolean;
}

export interface MessageResponse {
  session_id: string;
  turn: number;
  say: string;
  path: string[];
  build: string[];
  push: string | null;
  next_probe: string | null;
  mode: string;
  latency_ms: number;
  answer_summary: string;
  warning: string | null;
  debug: DebugInfo | null;
}

export interface TurnSummary {
  turn: number;
  interviewer_text: string;
  say: string;
  path: string[];
  build: string[];
  push: string | null;
  next_probe: string | null;
  mode: string;
  latency_ms: number;
  created_at: string;
}

export interface SessionDetail {
  session_id: string;
  created_at: string;
  turn_count: number;
  turns: TurnSummary[];
  state: Record<string, unknown>;
}

export interface TranscriptionResponse {
  text: string;
  latency_ms: number;
  model: string;
}

export type StreamEvent =
  | {
      type: "routing";
      mode: string;
      domains: string[];
      budget: string;
      router_latency_ms: number;
      router_skipped: boolean;
    }
  | {
      type: "specialists";
      selected: string[];
      specialist_latency_ms: number;
      failures: string[];
    }
  | { type: "say"; text: string }
  | { type: "final"; payload: MessageResponse }
  | { type: "error"; message: string };

/** What the answer pane renders — either a finished turn or a streaming one. */
export interface DisplayAnswer {
  turn: number | null;
  say: string;
  path: string[];
  build: string[];
  push: string | null;
  next_probe: string | null;
  mode: string;
  latency_ms: number | null;
  warning: string | null;
  streaming: boolean;
}
