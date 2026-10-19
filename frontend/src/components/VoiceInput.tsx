import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../lib/api";
import { Icon } from "./icons";

/**
 * Voice typing for the task box.
 *
 * Whisper (through the company's own Groq key) when the company has one;
 * otherwise the browser's built-in recogniser. Whisper is more accurate,
 * especially with accents, but the browser one costs nothing and needs
 * no setup. If neither is possible the button does not appear at all.
 *
 * Voice only ever fills in the text. The task is still sent with the
 * Assign button, so a misheard word can be fixed first.
 */

type Engine = "whisper" | "browser";
type Phase = "idle" | "listening" | "transcribing";

// Long enough for a detailed request, short enough that a forgotten
// recording does not run on.
const MAX_SECONDS = 60;

// The Web Speech API is still prefixed in Chrome and Safari, and not in
// TypeScript's DOM types.
type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  onresult: ((event: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
};

function browserRecognition(): (new () => Recognition) | null {
  const w = window as unknown as Record<string, unknown>;
  return ((w.SpeechRecognition ?? w.webkitSpeechRecognition) as (new () => Recognition) | undefined) ?? null;
}

function canRecord(): boolean {
  return typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
}

/** The first recording format this browser supports that Whisper accepts. */
function recordingType(): string | undefined {
  return ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"].find((t) =>
    MediaRecorder.isTypeSupported(t),
  );
}

export default function VoiceInput({
  onText,
  onError,
}: {
  onText: (text: string) => void;
  onError: (message: string | null) => void;
}) {
  const [engine, setEngine] = useState<Engine | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [seconds, setSeconds] = useState(0);
  const stopRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    let live = true;
    api
      .get<{ engine: Engine }>(`/me/speech`)
      .then((r) => {
        if (!live) return;
        // Whisper needs a recorder; without one, fall back to the browser.
        if (r.engine === "whisper" && canRecord()) setEngine("whisper");
        else if (browserRecognition()) setEngine("browser");
        else setEngine(null);
      })
      .catch(() => live && setEngine(browserRecognition() ? "browser" : null));
    return () => {
      live = false;
      stopRef.current?.();
    };
  }, ["me"]);

  // The timer, and the automatic stop at the limit.
  useEffect(() => {
    if (phase !== "listening") return;
    setSeconds(0);
    const started = Date.now();
    const timer = window.setInterval(() => {
      const elapsed = Math.floor((Date.now() - started) / 1000);
      setSeconds(elapsed);
      if (elapsed >= MAX_SECONDS) stopRef.current?.();
    }, 250);
    return () => window.clearInterval(timer);
  }, [phase]);

  if (!engine) return null;

  async function startWhisper() {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      onError("Microphone access was blocked. Allow it in the browser to use voice typing.");
      return;
    }
    const type = recordingType();
    const recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      stopRef.current = null;
      const blob = new Blob(chunks, { type: (recorder.mimeType || type || "audio/webm").split(";")[0] });
      if (!blob.size) {
        setPhase("idle");
        return;
      }
      setPhase("transcribing");
      try {
        const { text } = await api.upload<{ text: string }>(`/me/speech/transcribe`, blob);
        if (text) onText(text);
        else onError("No speech was heard. Try again a little closer to the microphone.");
      } catch (err) {
        onError(err instanceof ApiError ? err.message : "Voice typing failed. Try again.");
      } finally {
        setPhase("idle");
      }
    };
    stopRef.current = () => recorder.state !== "inactive" && recorder.stop();
    recorder.start();
    setPhase("listening");
  }

  function startBrowser() {
    const Ctor = browserRecognition();
    if (!Ctor) return;
    const rec = new Ctor();
    // Indian English understands both Indian and other English accents
    // well, and matches the people this product is built for first.
    rec.lang = navigator.language?.startsWith("en") ? navigator.language : "en-IN";
    rec.continuous = true;
    rec.interimResults = false;
    rec.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) onText(result[0].transcript.trim());
      }
    };
    rec.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        onError("Microphone access was blocked. Allow it in the browser to use voice typing.");
      } else if (event.error !== "no-speech" && event.error !== "aborted") {
        onError("The browser could not listen just now. Try again.");
      }
    };
    rec.onend = () => {
      stopRef.current = null;
      setPhase("idle");
    };
    stopRef.current = () => rec.stop();
    rec.start();
    setPhase("listening");
  }

  function toggle() {
    if (phase === "listening") {
      stopRef.current?.();
      return;
    }
    if (phase !== "idle") return;
    onError(null);
    if (engine === "whisper") void startWhisper();
    else startBrowser();
  }

  const listening = phase === "listening";
  const label = listening ? "Stop and use what I said" : "Speak the task";
  const engineName = engine === "whisper" ? "Whisper" : "Browser voice";

  return (
    <span className="flex items-center gap-2.5" data-coach="voice">
      <button
        type="button"
        onClick={toggle}
        disabled={phase === "transcribing"}
        aria-label={label}
        aria-pressed={listening}
        title={`${label} (${engineName})`}
        className={`grid h-11 w-11 place-items-center rounded-full border transition-colors ${
          listening
            ? "voice-rec border-transparent bg-bad text-bad-on"
            : "border-line2 text-muted hover:border-accent-line hover:text-ink"
        }`}
      >
        <Icon name={phase === "transcribing" ? "spinner" : listening ? "stop" : "mic"} size={18} strokeWidth={2} className={phase === "transcribing" ? "spin" : ""} />
      </button>
      <span className="text-[13px] text-muted" aria-live="polite">
        {listening
          ? `Listening… 0:${String(seconds).padStart(2, "0")}`
          : phase === "transcribing"
            ? "Writing it down…"
            : <span className="hidden sm:inline">Speak it · <span className="text-dim">{engineName}</span></span>}
      </span>
    </span>
  );
}
