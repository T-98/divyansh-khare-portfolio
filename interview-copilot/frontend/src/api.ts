import type {
  MessageResponse,
  SessionDetail,
  StreamEvent,
  TranscriptionResponse,
} from "./types";

async function unwrap<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export async function health(): Promise<{ status: string }> {
  return unwrap(await fetch("/health"));
}

export async function createSession(): Promise<{ session_id: string }> {
  return unwrap(await fetch("/api/sessions", { method: "POST" }));
}

export async function getSession(sessionId: string): Promise<SessionDetail> {
  return unwrap(await fetch(`/api/sessions/${sessionId}`));
}

export async function deleteSession(sessionId: string): Promise<void> {
  await fetch(`/api/sessions/${sessionId}`, { method: "DELETE" });
}

/** Blocking turn. Used when streaming is unavailable. */
export async function sendMessage(
  sessionId: string,
  text: string,
): Promise<MessageResponse> {
  return unwrap(
    await fetch(`/api/sessions/${sessionId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  );
}

/**
 * Streaming turn. EventSource cannot POST, so this reads the SSE frames off a
 * fetch body directly. `onEvent` fires for every frame; the `say` frames are
 * what put the opening line on screen while the rest is still generating.
 */
export async function streamMessage(
  sessionId: string,
  text: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/sessions/${sessionId}/messages/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
    signal,
  });

  if (!response.ok || !response.body) {
    throw new Error(`stream failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    let split = buffer.indexOf("\n\n");
    while (split !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (line) {
        try {
          onEvent(JSON.parse(line.slice(6)) as StreamEvent);
        } catch {
          /* ignore a malformed frame rather than killing the turn */
        }
      }
      split = buffer.indexOf("\n\n");
    }
  }
}

export async function transcribe(blob: Blob): Promise<TranscriptionResponse> {
  const form = new FormData();
  const extension = blob.type.includes("mp4") ? "mp4" : "webm";
  form.append("audio", blob, `clip.${extension}`);
  return unwrap(
    await fetch("/api/transcribe", { method: "POST", body: form }),
  );
}
