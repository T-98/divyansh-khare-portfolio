import { useCallback, useEffect, useRef, useState } from "react";

export type RecorderState = "idle" | "recording" | "transcribing" | "denied";

/**
 * Push-to-record microphone capture.
 *
 * Deliberately batch: record, stop, upload, get text back. A Realtime socket
 * would be lower latency but the interviewer's question is short and the
 * candidate needs to edit it before sending anyway.
 */
export function useRecorder(onTranscript: (text: string) => void, onError: (message: string) => void) {
  const [state, setState] = useState<RecorderState>("idle");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  const releaseMic = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => releaseMic, [releaseMic]);

  const pickMimeType = (): string | undefined => {
    // Safari only produces mp4; Chromium prefers webm/opus.
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
    return candidates.find((type) => MediaRecorder.isTypeSupported?.(type));
  };

  const start = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setState("denied");
      onError("This browser cannot record audio. Type the question instead.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };

      recorder.onstop = async () => {
        releaseMic();
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        chunksRef.current = [];
        if (blob.size < 512) {
          setState("idle");
          onError("Recording was too short.");
          return;
        }
        setState("transcribing");
        try {
          const { transcribe } = await import("../api");
          const result = await transcribe(blob);
          if (result.text) {
            onTranscript(result.text);
          } else {
            onError("Nothing was transcribed.");
          }
        } catch (error) {
          // The existing textarea content is never touched on failure.
          onError(error instanceof Error ? error.message : "Transcription failed.");
        } finally {
          setState("idle");
        }
      };

      recorder.start();
      recorderRef.current = recorder;
      setState("recording");
    } catch (error) {
      releaseMic();
      const denied =
        error instanceof DOMException &&
        (error.name === "NotAllowedError" || error.name === "SecurityError");
      setState(denied ? "denied" : "idle");
      onError(
        denied
          ? "Microphone permission denied. Type the question instead."
          : "Could not start the microphone.",
      );
    }
  }, [onError, onTranscript, releaseMic]);

  const stop = useCallback(() => {
    if (recorderRef.current?.state === "recording") {
      recorderRef.current.stop();
      recorderRef.current = null;
    }
  }, []);

  const toggle = useCallback(() => {
    if (state === "recording") stop();
    else if (state !== "transcribing") void start();
  }, [start, state, stop]);

  return { state, start, stop, toggle };
}
