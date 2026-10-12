import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { flushSync } from "react-dom";
import "./film.css";
import { CaptionBlock, SCENES, TOTAL_MS, s, type SceneDef } from "./scenes";

/**
 * The product film: a ~65 second walkthrough, played by the browser.
 *
 * It is a set of scenes rather than a video file, so it is sharp at any
 * size, weighs a few kilobytes, and stays in step with the real product.
 * The same component exports the MP4: in record mode it exposes
 * `window.__film.seek(ms)`, which renders the exact frame for any moment
 * by pausing every animation and setting its clock.
 */

const FULL = { w: 1280, h: 720 };
const COMPACT = { w: 740, h: 600 };
const TRANSITION_MS = 700;

const starts = SCENES.reduce<number[]>((acc, _scene, i) => {
  acc.push(i === 0 ? 0 : acc[i - 1] + SCENES[i - 1].duration);
  return acc;
}, []);

declare global {
  interface Window {
    __film?: { total: number; seek: (ms: number) => void; ready: boolean };
  }
}

interface Layer {
  index: number;
  leaving: boolean;
  /** When this layer's enter or exit transition began, in film time. */
  since: number;
}

function sceneAt(t: number): number {
  for (let i = SCENES.length - 1; i >= 0; i--) if (t >= starts[i]) return i;
  return 0;
}

function format(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function Film({
  mode = "player",
  only,
  autoPlay = true,
  className = "",
}: {
  /** player: chrome and chapters. record: bare stage for the exporter. */
  mode?: "player" | "record";
  /** Loop a single scene, without its caption (used beside a feature). */
  only?: string;
  autoPlay?: boolean;
  className?: string;
}) {
  const single = only ? SCENES.findIndex((sc) => sc.id === only) : -1;
  const compact = single >= 0;
  const size = compact ? COMPACT : FULL;
  const firstIndex = compact ? single : 0;
  // A looping single scene runs on its own clock that starts at 0.
  const offset = compact ? starts[single] : 0;
  const total = compact ? SCENES[single].duration : TOTAL_MS;

  const outer = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const fills = useRef<(HTMLSpanElement | null)[]>([]);
  const clock = useRef<HTMLSpanElement>(null);
  const t = useRef(0);
  const [scale, setScale] = useState(1);
  const [layers, setLayers] = useState<Layer[]>([
    { index: firstIndex, leaving: false, since: 0 },
  ]);
  const [epoch, setEpoch] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const userPaused = useRef(false);
  const visible = useRef(false);

  // ---- scale the fixed-size stage to whatever width it is given
  useLayoutEffect(() => {
    const el = outer.current;
    if (!el) return;
    const update = () => {
      const rect = el.getBoundingClientRect();
      setScale(Math.min(rect.width / size.w, rect.height / size.h || Infinity));
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [size.w, size.h]);

  const animations = useCallback(
    () => stage.current?.getAnimations({ subtree: true }) ?? [],
    [],
  );

  // ---- progress chrome, updated without re-rendering
  const paintProgress = useCallback(() => {
    if (compact) return;
    const now = t.current;
    SCENES.forEach((scene, i) => {
      const el = fills.current[i];
      if (!el) return;
      const p = Math.min(1, Math.max(0, (now - starts[i]) / scene.duration));
      el.style.transform = `scaleX(${p})`;
    });
    if (clock.current)
      clock.current.textContent = `${format(now)} / ${format(TOTAL_MS)}`;
  }, [compact]);

  // ---- the playback loop
  useEffect(() => {
    if (mode !== "player" || !playing) return;
    let last = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const dt = Math.min(100, now - last);
      last = now;
      const before = t.current;
      let next = before + dt;

      if (next >= total) {
        // Loop: start again from the top with a fresh mount.
        next = 0;
        t.current = 0;
        setLayers([{ index: firstIndex, leaving: false, since: 0 }]);
        setEpoch((e) => e + 1);
      } else {
        t.current = next;
        if (!compact) {
          const was = sceneAt(before);
          const now_ = sceneAt(next);
          if (now_ !== was) {
            setLayers([
              { index: was, leaving: true, since: starts[now_] },
              { index: now_, leaving: false, since: starts[now_] },
            ]);
          } else if (next - starts[now_] > TRANSITION_MS) {
            setLayers((current) =>
              current.length > 1 ? current.filter((l) => !l.leaving) : current,
            );
          }
        }
      }
      paintProgress();
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [mode, playing, total, compact, firstIndex, paintProgress]);

  // Until it first plays, show a poster: a moment where the scene is
  // fully composed, rather than every element waiting at its start.
  const started = useRef(false);
  const poster = compact ? total - 900 : 3800;

  // Freshly mounted scenes start running; keep them still if paused.
  useLayoutEffect(() => {
    if (mode !== "player" || playing) return;
    for (const animation of animations()) {
      animation.pause();
      if (!started.current) {
        const target = (animation.effect as KeyframeEffect | null)?.target as Element | null;
        const holder = target?.closest("[data-start]");
        animation.currentTime = Math.max(0, poster - Number(holder?.getAttribute("data-start") ?? 0));
      }
    }
  }, [layers, epoch, playing, mode, animations, poster]);

  const play = useCallback(() => {
    if (!started.current) {
      // Leave the poster: remount so the film starts from its first frame.
      started.current = true;
      t.current = 0;
      setEpoch((e) => e + 1);
    } else {
      animations().forEach((a) => a.play());
    }
    setPlaying(true);
  }, [animations]);

  const pause = useCallback(() => {
    animations().forEach((a) => a.pause());
    setPlaying(false);
  }, [animations]);

  // ---- play when on screen, pause when scrolled away
  useEffect(() => {
    if (mode !== "player" || !autoPlay) return;
    const el = outer.current;
    if (!el) return;
    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const observer = new IntersectionObserver(
      ([entry]) => {
        visible.current = entry.isIntersecting;
        if (entry.isIntersecting && !userPaused.current && !reduced) play();
        if (!entry.isIntersecting) pause();
      },
      { threshold: 0.35 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [mode, autoPlay, play, pause]);

  function jump(index: number) {
    started.current = true;
    t.current = starts[index];
    setLayers([{ index, leaving: false, since: starts[index] }]);
    setEpoch((e) => e + 1);
    paintProgress();
    if (!playing) {
      userPaused.current = false;
      setPlaying(true);
    }
  }

  function toggle() {
    if (playing) {
      userPaused.current = true;
      pause();
    } else {
      userPaused.current = false;
      play();
    }
  }

  // ---- fullscreen
  useEffect(() => {
    const onChange = () =>
      setFullscreen(document.fullscreenElement === outer.current);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  // ---- record mode: frame-exact seeking for the MP4 exporter
  useEffect(() => {
    if (mode !== "record") return;
    window.__film = {
      total: TOTAL_MS,
      ready: true,
      seek: (ms: number) => {
        const index = sceneAt(ms);
        const enterAge = ms - starts[index];
        const next: Layer[] =
          index > 0 && enterAge < TRANSITION_MS
            ? [
                { index: index - 1, leaving: true, since: starts[index] },
                { index, leaving: false, since: starts[index] },
              ]
            : [{ index, leaving: false, since: starts[index] }];
        flushSync(() => setLayers(next));
        for (const animation of animations()) {
          const target = (animation.effect as KeyframeEffect | null)
            ?.target as Element | null;
          // An animation the element no longer declares can linger once
          // it has been paused by script. Drop it, or it would be replayed.
          const name = (animation as CSSAnimation).animationName;
          if (target && name && !getComputedStyle(target).animationName.split(", ").includes(name)) {
            animation.cancel();
            continue;
          }
          const holder = target?.closest("[data-start]");
          const start = holder ? Number(holder.getAttribute("data-start")) : 0;
          animation.pause();
          animation.currentTime = Math.max(0, ms - start);
        }
      },
    };
    return () => {
      delete window.__film;
    };
  }, [mode, animations]);

  const current = layers[layers.length - 1].index;

  return (
    <div
      ref={outer}
      className={`relative w-full select-none overflow-hidden ${className}`}
      style={{
        aspectRatio: `${size.w} / ${size.h}`,
        background: "#0a0c18",
        ...(fullscreen
          ? {
              width: "100vw",
              height: "100vh",
              aspectRatio: "auto",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }
          : {}),
      }}
    >
      <div
        ref={stage}
        className="film"
        style={{
          position: "absolute",
          left: fullscreen ? `calc(50% - ${(size.w * scale) / 2}px)` : 0,
          top: fullscreen ? `calc(50% - ${(size.h * scale) / 2}px)` : 0,
          width: size.w,
          height: size.h,
          transform: `scale(${scale})`,
          transformOrigin: "0 0",
        }}
      >
        <Backdrop compact={compact} />
        {layers.map((layer) => (
          <SceneLayer
            key={`${layer.index}-${epoch}`}
            scene={SCENES[layer.index]}
            start={starts[layer.index] - offset}
            since={layer.since - offset}
            leaving={layer.leaving}
            compact={compact}
            firstFrame={
              layer.index === firstIndex && layer.since === starts[firstIndex]
            }
          />
        ))}
      </div>

      {mode === "player" && !compact && (
        <Chrome
          playing={playing}
          current={current}
          onToggle={toggle}
          onJump={jump}
          onFullscreen={() =>
            document.fullscreenElement
              ? void document.exitFullscreen()
              : void outer.current?.requestFullscreen()
          }
          fills={fills}
          clock={clock}
        />
      )}
      {mode === "player" && compact && (
        <button
          type="button"
          onClick={toggle}
          aria-label={playing ? "Pause animation" : "Play animation"}
          className="absolute bottom-3 right-3 flex h-9 w-9 items-center justify-center rounded-full bg-black/45 text-white opacity-70 backdrop-blur transition hover:opacity-100"
        >
          <PlayIcon playing={playing} />
        </button>
      )}
    </div>
  );
}

function Backdrop({ compact }: { compact: boolean }) {
  const glow = (color: string, style: CSSProperties, dur: number) => (
    <span
      style={{
        position: "absolute",
        width: 620,
        height: 620,
        borderRadius: 999,
        background: `radial-gradient(circle, ${color}, transparent 65%)`,
        animation: `f-drift ${dur}ms ease-in-out 0ms infinite both`,
        ...style,
      }}
    />
  );
  return (
    <div data-start={0} style={{ position: "absolute", inset: 0 }}>
      <div className="f-grid" />
      {glow(
        "rgba(123,147,255,.20)",
        { right: compact ? -260 : -120, top: -260 },
        16000,
      )}
      {glow("rgba(255,138,76,.12)", { left: -260, bottom: -320 }, 21000)}
    </div>
  );
}

function SceneLayer({
  scene,
  start,
  since,
  leaving,
  compact,
  firstFrame,
}: {
  scene: SceneDef;
  start: number;
  since: number;
  leaving: boolean;
  compact: boolean;
  firstFrame: boolean;
}) {
  const { Visual, caption } = scene;
  // Enter and exit live on separate wrappers. Swapping one animation for
  // another on the same element leaves the paused first one behind in
  // some browsers, which the frame-exact recorder would then replay.
  const enter =
    firstFrame && !compact
      ? `f-fade 900ms ease 0ms 1 both`
      : `f-scene-in ${TRANSITION_MS}ms cubic-bezier(.16,1,.3,1) 0ms 1 both`;
  const exit = leaving
    ? `f-scene-out 600ms cubic-bezier(.4,0,.2,1) 0ms 1 both`
    : undefined;

  return (
    <div
      data-start={start}
      style={{
        position: "absolute",
        inset: 0,
        animation: enter,
        zIndex: leaving ? 1 : 2,
        pointerEvents: "none",
      }}
    >
      <div
        data-start={since}
        style={{ position: "absolute", inset: 0, animation: exit }}
      >
        <div data-start={start} style={{ position: "absolute", inset: 0 }}>
          {!leaving && !firstFrame && (
            <span
              style={{
                position: "absolute",
                top: -100,
                bottom: -100,
                width: 160,
                zIndex: 40,
                background:
                  "linear-gradient(90deg, transparent, rgba(164,139,255,.35), rgba(255,138,76,.25), transparent)",
                animation: s("f-wipe", 0, 900, "cubic-bezier(.4,0,.2,1)"),
              }}
            />
          )}
          {compact || !caption ? (
            <div style={{ position: "absolute", inset: 0 }}>
              <Visual />
            </div>
          ) : (
            <>
              <div
                style={{
                  position: "absolute",
                  left: 72,
                  top: 0,
                  bottom: 0,
                  width: 380,
                  display: "flex",
                  alignItems: "center",
                }}
              >
                <CaptionBlock caption={caption} />
              </div>
              <div
                style={{
                  position: "absolute",
                  left: 500,
                  top: 60,
                  width: 740,
                  height: 600,
                }}
              >
                <Visual />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function PlayIcon({ playing }: { playing: boolean }) {
  return playing ? (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <rect x="6" y="5" width="4" height="14" rx="1" />
      <rect x="14" y="5" width="4" height="14" rx="1" />
    </svg>
  ) : (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z" />
    </svg>
  );
}

function Chrome({
  playing,
  current,
  onToggle,
  onJump,
  onFullscreen,
  fills,
  clock,
}: {
  playing: boolean;
  current: number;
  onToggle: () => void;
  onJump: (index: number) => void;
  onFullscreen: () => void;
  fills: React.MutableRefObject<(HTMLSpanElement | null)[]>;
  clock: React.RefObject<HTMLSpanElement>;
}) {
  return (
    <div className="film-player-bar absolute inset-x-0 bottom-0 z-10 flex items-end gap-3 px-3 pb-3 pt-10 text-white sm:gap-4 sm:px-5 sm:pb-4">
      <button
        type="button"
        onClick={onToggle}
        aria-label={playing ? "Pause the film" : "Play the film"}
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/15 backdrop-blur transition hover:bg-white/25"
      >
        <PlayIcon playing={playing} />
      </button>
      <div className="flex min-w-0 flex-1 gap-1.5 pb-1.5 sm:gap-2">
        {SCENES.map((scene, i) => (
          <button
            key={scene.id}
            type="button"
            onClick={() => onJump(i)}
            className="group flex min-w-0 flex-col gap-1.5 text-left"
            style={{ flex: scene.duration }}
            aria-label={`Jump to ${scene.label}`}
          >
            <span
              className={`hidden truncate text-[11px] font-medium transition sm:block ${i === current ? "text-white" : "text-white/55 group-hover:text-white/85"}`}
            >
              {scene.label}
            </span>
            <span className="film-chapter w-full">
              <span
                ref={(el) => (fills.current[i] = el)}
                style={{ transform: "scaleX(0)" }}
              />
            </span>
          </button>
        ))}
      </div>
      <span
        ref={clock}
        className="hidden shrink-0 pb-0.5 font-mono text-xs text-white/70 sm:block"
      >
        0:00 / {format(TOTAL_MS)}
      </span>
      <button
        type="button"
        onClick={onFullscreen}
        aria-label="Full screen"
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/10 transition hover:bg-white/20"
      >
        <svg
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        >
          <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
        </svg>
      </button>
    </div>
  );
}
