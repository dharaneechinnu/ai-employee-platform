import { useCallback, useEffect, useRef, useState } from "react";
import { BrandMark } from "../Layout";
import { Icon } from "../icons";

/**
 * The first thing a new person sees after signing in: three short,
 * animated slides on what this product is, then an offer to show them
 * around. Skippable at every point, and replayable from the help button.
 */

const SLIDES = [
  {
    kicker: "Welcome",
    title: "Meet your AI team",
    body: "AI Employees do real work in your real apps: reading email, checking data, drafting replies. Each one has a job, tools and limits.",
    visual: "team",
  },
  {
    kicker: "Safety",
    title: "You stay in control",
    body: "Reading happens on its own. Anything that sends or changes something waits for a person, with the full action shown first.",
    visual: "control",
  },
  {
    kicker: "Live",
    title: "Watch them work",
    body: "Every step streams live and stays on record, with what it cost. Ask in plain words, or just say it out loud.",
    visual: "live",
  },
] as const;

// Plain text: the words appear with the slide, without per-word motion.
function Words({ text }: { text: string; delay?: number }) {
  return <>{text}</>;
}

function TeamVisual() {
  const people = [
    { n: "R", name: "Ravi", job: "Checks the data", hue: "var(--accent)", dur: 16, start: 0 },
    { n: "K", name: "Kiran", job: "Reads the inbox", hue: "var(--run)", dur: 16, start: -5.33 },
    { n: "M", name: "Meera", job: "Drafts replies", hue: "var(--spark)", dur: 16, start: -10.66 },
  ];
  return (
    <div className="welcome-stage">
      <div className="welcome-orbit-ring" />
      <div className="welcome-orbit-ring welcome-orbit-ring-2" />
      <div className="welcome-core">
        <BrandMark size={64} />
      </div>
      {people.map((p) => (
        <div key={p.n} className="welcome-orbiter" style={{ animationDuration: `${p.dur}s`, animationDelay: `${p.start}s` }}>
          <div className="welcome-person" style={{ animationDuration: `${p.dur}s`, animationDelay: `${p.start}s` }}>
            <span className="welcome-avatar" style={{ background: `linear-gradient(135deg, ${p.hue}, var(--accent2))` }}>
              {p.n}
            </span>
          </div>
        </div>
      ))}
      <div className="welcome-chips">
        {people.map((p, i) => (
          <span key={p.n} className="welcome-tag" style={{ animationDelay: `${0.3 + i * 0.15}s, ${i * 1.2}s` }}>
            <b>{p.name}</b> {p.job.toLowerCase()}
          </span>
        ))}
      </div>
    </div>
  );
}

function ControlVisual() {
  return (
    <div className="welcome-stage">
      <div className="welcome-approval">
        <div className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-ask-soft text-ask-text">
            <Icon name="approvals" size={18} />
          </span>
          <span className="text-sm font-medium">
            Ravi wants to <span className="text-ask-text">send a Gmail email</span>
          </span>
        </div>
        <div className="welcome-mail">
          <span className="text-xs text-dim">To</span>
          <span className="text-[13px]">ops-team@victopia.com</span>
          <span className="mt-1 text-xs text-dim">Message</span>
          <span className="welcome-lines">
            <i />
            <i />
          </span>
        </div>
        <div className="welcome-hold">
          <span className="welcome-hold-fill" />
          <span className="relative flex items-center gap-2">
            <Icon name="check" size={16} strokeWidth={2.4} /> Hold to approve
          </span>
        </div>
      </div>
      <div className="welcome-shield">
        <Icon name="shield" size={30} />
      </div>
    </div>
  );
}

function LiveVisual() {
  const rows = [
    { t: "Looked up company memory", d: "found ERR_4021", tone: "ok" },
    { t: "Looked up data (read-only)", d: "1,284 failed checkouts", tone: "ok" },
    { t: "Asked a colleague", d: "Kiran is helping", tone: "brand" },
    { t: "Waiting for approval", d: "send a Gmail email", tone: "ask" },
    { t: "Finished", d: "9 steps · all on record", tone: "ok" },
  ];
  return (
    <div className="welcome-stage">
      <div className="welcome-timeline">
        {rows.map((r, i) => (
          <div key={r.t} className="welcome-step" style={{ animationDelay: `${0.2 + i * 0.55}s` }}>
            <span className={`welcome-step-dot tone-${r.tone}`}>
              <Icon name={r.tone === "ask" ? "approvals" : r.tone === "brand" ? "tree" : "check"} size={13} strokeWidth={2.4} />
            </span>
            <span className="flex min-w-0 flex-col">
              <span className="truncate text-[13px] font-medium">{r.t}</span>
              <span className="truncate text-xs text-muted">{r.d}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Welcome({ name, onDone }: { name: string | null; onDone: (tour: boolean) => void }) {
  const [index, setIndex] = useState(0);
  const [dir, setDir] = useState<1 | -1>(1);
  const [leaving, setLeaving] = useState(false);
  const primary = useRef<HTMLButtonElement>(null);
  const slide = SLIDES[index];
  const last = index === SLIDES.length - 1;

  const finish = useCallback(
    (tour: boolean) => {
      setLeaving(true);
      window.setTimeout(() => onDone(tour), 450);
    },
    [onDone],
  );

  const go = useCallback(
    (to: number) => {
      if (to < 0 || to >= SLIDES.length) return;
      setDir(to > index ? 1 : -1);
      setIndex(to);
    },
    [index],
  );

  useEffect(() => {
    primary.current?.focus({ preventScroll: true });
  }, [index]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") finish(false);
      else if (e.key === "ArrowRight") (last ? finish(true) : go(index + 1));
      else if (e.key === "ArrowLeft") go(index - 1);
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [index, last, go, finish]);

  return (
    <div className={`welcome-root ${leaving ? "welcome-out" : ""}`} role="dialog" aria-modal="true" aria-labelledby="welcome-title">
      <div className="welcome-blob welcome-blob-a" aria-hidden="true" />
      <div className="welcome-blob welcome-blob-b" aria-hidden="true" />
      <div className="welcome-grid" aria-hidden="true" />

      <div className="welcome-card">
        <div key={`v-${index}`} className={`welcome-visual ${dir > 0 ? "from-right" : "from-left"}`} aria-hidden="true">
          {slide.visual === "team" && <TeamVisual />}
          {slide.visual === "control" && <ControlVisual />}
          {slide.visual === "live" && <LiveVisual />}
        </div>

        <div key={`t-${index}`} className="welcome-text">
          <span className="welcome-kicker">
            {index === 0 && name ? `Welcome, ${name}` : slide.kicker}
          </span>
          <h2 id="welcome-title" className="welcome-title font-display">
            <Words text={slide.title} />
          </h2>
          <p className="welcome-body">
            <Words text={slide.body} delay={260} />
          </p>
        </div>

        <div className="welcome-foot">
          <div className="flex items-center gap-2" role="tablist" aria-label="Slides">
            {SLIDES.map((s, i) => (
              <button
                key={s.title}
                type="button"
                role="tab"
                aria-selected={i === index}
                aria-label={`Slide ${i + 1}: ${s.title}`}
                className={`welcome-dot ${i === index ? "on" : ""}`}
                onClick={() => go(i)}
              />
            ))}
          </div>
          <span className="flex-1" />
          {!last && (
            <button type="button" className="welcome-skip" onClick={() => finish(false)}>
              Skip
            </button>
          )}
          {index > 0 && (
            <button type="button" className="btn btn-ghost" onClick={() => go(index - 1)}>
              Back
            </button>
          )}
          <button
            ref={primary}
            type="button"
            className="btn btn-primary"
            onClick={() => (last ? finish(true) : go(index + 1))}
          >
            {last ? "Show me around" : "Next"}
            <Icon name="arrow" size={16} strokeWidth={2.3} />
          </button>
        </div>
      </div>
    </div>
  );
}
