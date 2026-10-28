import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { useAuth } from "../../lib/auth";
import { readCompat } from "../../lib/storage";
import { Icon, type IconName } from "../icons";
import { TOURS, type CoachStep, type Tour } from "./tours";
import Welcome from "./Welcome";

/**
 * Coachmarks: a guided spotlight that teaches each screen the first time
 * someone opens it, and each feature the first time it appears.
 *
 * How it works:
 * - A tour is a list of steps; each step points at an element marked
 *   `data-coach="name"`. Steps whose element is missing or hidden (a
 *   panel that is closed, a button only shown on wide screens) are
 *   skipped, so one tour fits every screen size.
 * - Page tours start on first visit; feature tours start when their
 *   element first appears (opening a panel, a first approval).
 * - The spotlight is a hole in a full-screen mask. It glides between
 *   steps on a spring, animated by one requestAnimationFrame loop that
 *   writes straight to the DOM, so React does not re-render 60 times a
 *   second.
 * - What has been seen is remembered per person in this browser. If
 *   storage is unavailable, tips still work; they just come back.
 */

type Store = { intro: boolean; seen: string[]; off: boolean };

const EMPTY: Store = { intro: false, seen: [], off: false };

function load(key: string): Store {
  try {
    const raw = readCompat(key, key.replace("baton.", "ai-employees."));
    return raw ? { ...EMPTY, ...(JSON.parse(raw) as Partial<Store>) } : EMPTY;
  } catch {
    return EMPTY;
  }
}

function save(key: string, store: Store): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(store));
  } catch {
    /* private window or blocked storage: tips simply show again */
  }
}

type CoachApi = {
  /** Show this page's tour again, even if seen. */
  tourThisPage: () => void;
  /** Show the welcome intro again. */
  replayIntro: () => void;
  hasPageTour: boolean;
  tipsOff: boolean;
  setTipsOff: (off: boolean) => void;
};

const CoachContext = createContext<CoachApi | null>(null);

function useCoach(): CoachApi {
  const api = useContext(CoachContext);
  if (!api) throw new Error("useCoach needs <CoachProvider>");
  return api;
}

function findTarget(name: string): HTMLElement | null {
  const nodes = document.querySelectorAll<HTMLElement>(`[data-coach="${name}"]`);
  for (const el of nodes) {
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (r.width > 0 && r.height > 0 && style.visibility !== "hidden") return el;
  }
  return null;
}

/** Screenshot and video scripts drive a robot browser; tips would only
 * get in their way. A test that wants them sets `coach-force`. */
function automated(): boolean {
  try {
    return navigator.webdriver && window.sessionStorage.getItem("coach-force") !== "1";
  } catch {
    return navigator.webdriver;
  }
}

function usable(steps: CoachStep[]): CoachStep[] {
  return steps.filter((s) => true && (!s.target || findTarget(s.target)));
}

export function CoachProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  const location = useLocation();
  const key = `baton.coach.v1.${me?.id ?? "anon"}`;
  const [store, setStore] = useState<Store>(() => load(key));
  const [active, setActive] = useState<{ tour: Tour; steps: CoachStep[] } | null>(null);
  const [showIntro, setShowIntro] = useState(false);

  useEffect(() => setStore(load(key)), [key]);

  const update = useCallback(
    (change: (s: Store) => Store) =>
      setStore((current) => {
        const next = change(current);
        save(key, next);
        return next;
      }),
    [key],
  );

  // First sign-in: the welcome intro, once.
  useEffect(() => {
    if (me && !store.intro && !automated()) {
      const t = window.setTimeout(() => setShowIntro(true), 600);
      return () => window.clearTimeout(t);
    }
  }, [me, store.intro]);

  const start = useCallback(
    (tour: Tour) => {
      const steps = usable(tour.steps);
      if (steps.length) setActive({ tour, steps });
      return steps.length > 0;
    },
    [true],
  );

  const finish = useCallback(
    (tour: Tour) => {
      setActive(null);
      update((s) => (s.seen.includes(tour.id) ? s : { ...s, seen: [...s.seen, tour.id] }));
    },
    [update],
  );

  const ready = !!me && store.intro && !showIntro && !active && !store.off && !automated();

  // Page tours: the first visit to a screen, once its content has loaded.
  const pageTour = TOURS.find((t) => t.route === location.pathname);
  useEffect(() => {
    if (!ready || !pageTour || store.seen.includes(pageTour.id)) return;
    let tries = 0;
    // Retry briefly: the elements arrive with the page's data.
    // A slow network or a cold page can take several seconds.
    const timer = window.setInterval(() => {
      tries += 1;
      if (start(pageTour) || tries > 20) window.clearInterval(timer);
    }, 600);
    return () => window.clearInterval(timer);
  }, [ready, pageTour, store.seen, start]);

  // Feature tours: the first time their element appears on screen.
  useEffect(() => {
    if (!ready) return;
    const pending = TOURS.filter((t) => t.appears && !store.seen.includes(t.id));
    if (!pending.length) return;
    let frame = 0;
    const check = () => {
      frame = 0;
      for (const tour of pending) {
        if (tour.appears && findTarget(tour.appears)) {
          // A beat later, so the panel has finished its own entrance.
          window.setTimeout(() => start(tour), 650);
          observer.disconnect();
          return;
        }
      }
    };
    const observer = new MutationObserver(() => {
      if (!frame) frame = window.requestAnimationFrame(check);
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "style"] });
    check();
    return () => {
      observer.disconnect();
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [ready, store.seen, start]);

  const api = useMemo<CoachApi>(
    () => ({
      tourThisPage: () => {
        if (pageTour) start(pageTour);
      },
      replayIntro: () => setShowIntro(true),
      hasPageTour: !!pageTour,
      tipsOff: store.off,
      setTipsOff: (off) => update((s) => ({ ...s, off })),
    }),
    [pageTour, start, store.off, update],
  );

  return (
    <CoachContext.Provider value={api}>
      {children}
      {showIntro && (
        <Welcome
          name={me?.full_name?.split(" ")[0] ?? null}
          onDone={(tour) => {
            setShowIntro(false);
            update((s) => ({ ...s, intro: true, off: tour ? false : s.off }));
            if (tour && pageTour) window.setTimeout(() => start(pageTour), 500);
          }}
        />
      )}
      {active && (
        <Spotlight
          key={active.tour.id}
          steps={active.steps}
          onDone={() => finish(active.tour)}
          onTurnOff={() => {
            finish(active.tour);
            update((s) => ({ ...s, off: true }));
          }}
        />
      )}
    </CoachContext.Provider>
  );
}

// ---------------------------------------------------------------- spotlight

type Rect = { x: number; y: number; w: number; h: number };

const PAD = 8;
const GAP = 16;
const MARGIN = 12;

function prefersReducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

function Spotlight({ steps, onDone, onTurnOff }: { steps: CoachStep[]; onDone: () => void; onTurnOff: () => void }) {
  const [index, setIndex] = useState(0);
  const [leaving, setLeaving] = useState(false);
  const [nudge, setNudge] = useState(0);
  const step = steps[index];
  const last = index === steps.length - 1;

  const hole = useRef<SVGRectElement>(null);
  const ring = useRef<HTMLDivElement>(null);
  const glow = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const arrow = useRef<HTMLDivElement>(null);
  const primary = useRef<HTMLButtonElement>(null);
  const shown = useRef<Rect | null>(null);
  const targetRef = useRef<Rect>({ x: 0, y: 0, w: 0, h: 0 });

  // Bring the step's element into view when the step changes.
  useEffect(() => {
    const el = step.target ? findTarget(step.target) : null;
    if (el) {
      const r = el.getBoundingClientRect();
      if (r.top < 70 || r.bottom > window.innerHeight - 40) {
        el.scrollIntoView({ block: "center", behavior: prefersReducedMotion() ? "auto" : "smooth" });
      }
    }
    primary.current?.focus({ preventScroll: true });
  }, [step]);

  // One animation loop for the whole overlay.
  useEffect(() => {
    let frame = 0;
    const reduce = prefersReducedMotion();
    const tick = () => {
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const el = step.target ? findTarget(step.target) : null;
      if (el) {
        const r = el.getBoundingClientRect();
        targetRef.current = { x: r.left - PAD, y: r.top - PAD, w: r.width + PAD * 2, h: r.height + PAD * 2 };
      } else {
        targetRef.current = { x: vw / 2, y: vh / 2, w: 0, h: 0 };
      }

      const t = targetRef.current;
      if (!shown.current || reduce) shown.current = { ...t };
      else {
        // Ease towards the target with no overshoot: it glides and settles.
        const s = shown.current;
        for (const k of ["x", "y", "w", "h"] as const) {
          s[k] += (t[k] - s[k]) * 0.2;
        }
      }
      const s = shown.current;

      if (hole.current) {
        hole.current.setAttribute("x", String(s.x));
        hole.current.setAttribute("y", String(s.y));
        hole.current.setAttribute("width", String(Math.max(0, s.w)));
        hole.current.setAttribute("height", String(Math.max(0, s.h)));
        hole.current.setAttribute("rx", String(Math.min(18, Math.max(0, s.h) / 2)));
      }
      if (ring.current) {
        ring.current.style.transform = `translate3d(${s.x}px, ${s.y}px, 0)`;
        ring.current.style.width = `${Math.max(0, s.w)}px`;
        ring.current.style.height = `${Math.max(0, s.h)}px`;
        ring.current.style.opacity = s.w > 4 ? "1" : "0";
      }
      if (glow.current) {
        glow.current.style.transform = `translate3d(${s.x + s.w / 2 - 300}px, ${s.y + s.h / 2 - 300}px, 0)`;
      }

      // Place the card beside the hole wherever it fits best.
      if (card.current) {
        const cw = card.current.offsetWidth;
        const ch = card.current.offsetHeight;
        let left: number;
        let top: number;
        let side: "top" | "bottom" | "none" = "none";
        if (s.w < 4) {
          left = vw / 2 - cw / 2;
          top = vh / 2 - ch / 2;
        } else if (s.y + s.h + GAP + ch <= vh - MARGIN) {
          side = "bottom";
          top = s.y + s.h + GAP;
          left = s.x + s.w / 2 - cw / 2;
        } else if (s.y - GAP - ch >= MARGIN) {
          side = "top";
          top = s.y - GAP - ch;
          left = s.x + s.w / 2 - cw / 2;
        } else if (s.x + s.w + GAP + cw <= vw - MARGIN) {
          top = s.y + s.h / 2 - ch / 2;
          left = s.x + s.w + GAP;
        } else if (s.x - GAP - cw >= MARGIN) {
          top = s.y + s.h / 2 - ch / 2;
          left = s.x - GAP - cw;
        } else {
          // Tall element on a small screen: float the card at the bottom.
          top = vh - ch - MARGIN;
          left = vw / 2 - cw / 2;
        }
        left = Math.min(Math.max(left, MARGIN), vw - cw - MARGIN);
        top = Math.min(Math.max(top, MARGIN), vh - ch - MARGIN);
        card.current.style.transform = `translate3d(${Math.round(left)}px, ${Math.round(top)}px, 0)`;

        if (arrow.current) {
          if (side === "none") arrow.current.style.opacity = "0";
          else {
            const ax = Math.min(Math.max(s.x + s.w / 2 - left, 22), cw - 22);
            arrow.current.style.opacity = "1";
            arrow.current.style.left = `${ax - 7}px`;
            arrow.current.style.top = side === "bottom" ? "-7px" : `${ch - 7}px`;
            arrow.current.dataset.side = side;
          }
        }
      }
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [step]);

  const close = useCallback(
    (done: () => void) => {
      setLeaving(true);
      window.setTimeout(done, prefersReducedMotion() ? 0 : 200);
    },
    [],
  );

  const next = useCallback(() => {
    if (!last) {
      setIndex((i) => i + 1);
      return;
    }
    close(onDone);
  }, [last, close, onDone]);

  const back = useCallback(() => setIndex((i) => Math.max(0, i - 1)), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(onDone);
      else if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") back();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, back, close, onDone]);

  return (
    <div className={`coach-root ${leaving ? "coach-out" : ""}`} role="dialog" aria-modal="true" aria-labelledby="coach-title">
      {/* The dimmed screen with a hole; a click outside nudges the card. */}
      <svg className="coach-mask" width="100%" height="100%" aria-hidden="true" onClick={() => setNudge((n) => n + 1)}>
        <defs>
          <mask id="coach-hole">
            <rect width="100%" height="100%" fill="white" />
            <rect ref={hole} fill="black" />
          </mask>
        </defs>
        <rect width="100%" height="100%" fill="var(--coach-dim)" mask="url(#coach-hole)" />
      </svg>
      <div ref={glow} className="coach-glow" aria-hidden="true" />
      <div ref={ring} className="coach-ring" aria-hidden="true">
        <span key={index} className="coach-ping" />
      </div>

      <div ref={card} className="coach-pos">
        <div key={`${index}-${nudge}`} className={`coach-card ${nudge ? "coach-nudge" : ""}`}>
          <div ref={arrow} className="coach-arrow" aria-hidden="true" />
          <div className="flex items-center gap-2.5">
            <span className="coach-badge">
              <Icon name={(step.icon ?? "sparkle") as IconName} size={17} strokeWidth={2} />
            </span>
            <span className="flex-1 font-mono text-xs uppercase tracking-[0.14em] text-dim">
              Tip {index + 1} of {steps.length}
            </span>
            <button type="button" className="coach-x" aria-label="Close tips" onClick={() => close(onDone)}>
              <Icon name="x" size={16} />
            </button>
          </div>
          <h2 id="coach-title" className="coach-title font-display">
            {step.title}
          </h2>
          <p className="coach-body">{step.body}</p>
          <div className="flex items-center gap-2">
            <div className="flex flex-1 items-center gap-1.5" aria-hidden="true">
              {steps.map((_, i) => (
                <span key={i} className={`coach-dot ${i === index ? "on" : i < index ? "done" : ""}`} />
              ))}
            </div>
            {index > 0 && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={back}>
                Back
              </button>
            )}
            <button ref={primary} type="button" className="btn btn-primary btn-sm" onClick={next}>
              {last ? "Got it" : "Next"}
              <Icon name={last ? "check" : "arrow"} size={14} strokeWidth={2.4} />
            </button>
          </div>
          {last && (
            <button type="button" className="coach-off" onClick={() => close(onTurnOff)}>
              Don't show tips like this
            </button>
          )}
        </div>
      </div>

    </div>
  );
}

// ---------------------------------------------------------------- help button

/** A small floating button: tour this page again, or replay the intro. */
export function CoachHelp() {
  const { tourThisPage, replayIntro, hasPageTour, tipsOff, setTipsOff } = useCoach();
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => !wrap.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={wrap} className="coach-help">
      {open && (
        <div className="coach-help-menu" role="menu">
          {hasPageTour && (
            <button type="button" role="menuitem" onClick={() => (setOpen(false), tourThisPage())}>
              <Icon name="sparkle" size={16} /> Tour this page
            </button>
          )}
          <button type="button" role="menuitem" onClick={() => (setOpen(false), replayIntro())}>
            <Icon name="eye" size={16} /> Replay the welcome
          </button>
          <button type="button" role="menuitem" onClick={() => setTipsOff(!tipsOff)}>
            <Icon name={tipsOff ? "check" : "x"} size={16} /> {tipsOff ? "Turn tips back on" : "Turn off new tips"}
          </button>
        </div>
      )}
      <button
        type="button"
        className="coach-help-btn"
        aria-label="Help and tours"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span aria-hidden="true">?</span>
      </button>
    </div>
  );
}
