import { useEffect, useRef, useState } from "react";

/**
 * A video that behaves like part of the page, not a player: no
 * controls, muted, looping, and it plays only while it is on screen.
 *
 * Browsers allow muted video to start on its own, so no click is
 * needed. Off screen it pauses, which saves battery and means it
 * starts from where the visitor left it. People who ask for reduced
 * motion get the still poster instead.
 *
 * `sound` adds one small button: browsers play sound only after a
 * click, so the video starts muted and the visitor can turn it on.
 */
export function AutoVideo({
  src,
  poster,
  label,
  sound = false,
  className = "",
}: {
  src: string;
  poster: string;
  label: string;
  sound?: boolean;
  className?: string;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [muted, setMuted] = useState(true);

  useEffect(() => {
    const el = video.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) void el.play().catch(() => {});
        else el.pause();
      },
      { threshold: 0.3 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  function toggleSound() {
    const el = video.current;
    if (!el) return;
    el.muted = !el.muted;
    if (!el.muted) {
      // Start from the top so the voiceover is heard from its first line.
      el.currentTime = 0;
      void el.play().catch(() => {});
    }
    setMuted(el.muted);
  }

  return (
    <div className="relative">
      <video
        ref={video}
        className={`block h-auto w-full ${className}`}
        src={src}
        poster={poster}
        muted
        loop
        playsInline
        preload="metadata"
        aria-label={label}
        disablePictureInPicture
        disableRemotePlayback
      />
      {sound && (
        <button
          type="button"
          onClick={toggleSound}
          aria-pressed={!muted}
          className="absolute bottom-4 right-4 inline-flex items-center gap-2 rounded-full border border-white/20 bg-black/60 px-4 py-2.5 text-sm font-medium text-white backdrop-blur transition hover:-translate-y-px hover:bg-black/75"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M11 5L6 9H2v6h4l5 4V5z" />
            <path d={muted ? "M16 9l5 6M21 9l-5 6" : "M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"} />
          </svg>
          {muted ? "Sound on" : "Sound off"}
        </button>
      )}
    </div>
  );
}
