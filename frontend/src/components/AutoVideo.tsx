import { useEffect, useRef } from "react";

/**
 * A video that behaves like part of the page, not a player: no
 * controls, muted, looping, and it plays only while it is on screen.
 *
 * Browsers allow muted video to start on its own, so no click is
 * needed. Off screen it pauses, which saves battery and means it
 * starts from where the visitor left it. People who ask for reduced
 * motion get the still poster instead.
 */
export function AutoVideo({ src, poster, label, className = "" }: { src: string; poster: string; label: string; className?: string }) {
  const video = useRef<HTMLVideoElement>(null);

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

  return (
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
  );
}
