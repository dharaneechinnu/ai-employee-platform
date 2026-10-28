import { Link } from "react-router-dom";
import { AutoVideo } from "../components/AutoVideo";
import { Icon, type IconName } from "../components/icons";
import { BrandMark } from "../components/Layout";
import { ThemeToggle } from "../components/ui";
import { useAuth } from "../lib/auth";

/**
 * The public product overview: what Baton is, in one film and
 * four features. Each feature is shown by its own scene from the film,
 * looping beside the words, so the page and the video never disagree.
 */

interface Feature {
  id: string;
  scene: string;
  alt: string;
  kicker: string;
  title: string;
  body: string;
  points: { icon: IconName; text: string }[];
}

const FEATURES: Feature[] = [
  {
    id: "live",
    alt: "A run streaming its steps live, with steps taken, AI usage and cost",
    scene: "assign",
    kicker: "Ask and watch",
    title: "Ask in plain words. Watch every step.",
    body: "Type what you need in chat, the way you would ask a friend. Set up your own helpers by answering three plain questions. Every thought, tool call and result streams live.",
    points: [
      { icon: "helpers", text: "Guided setup: what it does, what it must never do, when to ask you" },
      { icon: "terminal", text: "A live, replayable log of every step, token and cost" },
      { icon: "tree", text: "Bigger questions are split between specialists, shown as a live tree" },
    ],
  },
  {
    id: "safety",
    alt: "An approval request showing the full email before you agree",
    scene: "approval",
    kicker: "Safety and approvals",
    title: "Anything risky waits for you.",
    body: "For every tool, you choose Always allow, Ask me first, or Blocked. A paused run waits safely, then picks up exactly where it stopped.",
    points: [
      { icon: "approvals", text: "Approve from the app, your inbox or Slack, with the full action shown" },
      { icon: "lock", text: "Reading is automatic, sending asks first, catastrophic actions are blocked for everyone" },
      { icon: "shield", text: "Keys and tokens never enter the model's prompt, so injected text cannot steal them" },
    ],
  },
  {
    id: "connect",
    alt: "Google Workspace connected, with Always allow, Ask me first or Blocked for each tool",
    scene: "connect",
    kicker: "Connected apps",
    title: "One click to the tools you already use.",
    body: "Connect Google Workspace or Microsoft 365 once, and your assistant can search mail, draft replies, check calendars and read files. Nothing to paste, nothing to copy.",
    points: [
      { icon: "mail", text: "Gmail and Outlook: search, read, draft, and send with approval" },
      { icon: "calendar", text: "Google Calendar and Outlook: see the week, create events" },
      { icon: "folder", text: "Drive and OneDrive, read-only by permission, not just by promise" },
    ],
  },
  {
    id: "memory",
    alt: "Your memory, searchable by meaning and exact words",
    scene: "memory",
    kicker: "Memory and your own key",
    title: "It learns how you work. You hold the keys.",
    body: "Your memory is recalled by meaning, so what you said once helps every later chat. Bring your own model key; your bill stays yours.",
    points: [
      { icon: "memory", text: "Your memory, searched by meaning; forget anything, any time" },
      { icon: "providers", text: "Bring your own key: Gemini, OpenRouter and more" },
      { icon: "people", text: "Your account is sealed off; whoever runs the server sees counts, never content" },
    ],
  },
];

const WORKS_WITH = ["Gmail", "Google Calendar", "Google Drive", "Outlook", "OneDrive", "Slack", "PostgreSQL", "Gemini", "OpenRouter"];

const STEPS: { icon: IconName; title: string; body: string }[] = [
  { icon: "link", title: "Connect", body: "Sign in to Google or Microsoft once. Set what needs your approval." },
  { icon: "tasks", title: "Ask", body: "Type what you need in chat and watch it happen, step by step." },
  { icon: "helpers", title: "Make it yours", body: "Set up your own helpers in three plain answers and pick their tools." },
];

export default function Product() {
  const { me } = useAuth();
  const primary = me ? { to: "/chat", label: "Open your chat" } : { to: "/register", label: "Create your account" };

  return (
    <div className="min-h-screen bg-bg text-ink">
      {/* ---------------------------------------------------- nav */}
      <header className="sticky top-0 z-30 border-b border-line backdrop-blur-xl" style={{ background: "color-mix(in srgb, var(--bg) 78%, transparent)" }}>
        <nav className="mx-auto flex max-w-[1200px] items-center gap-3 px-4 py-3 sm:px-6">
          <Link to="/" className="flex items-center gap-2.5">
            <BrandMark size={32} />
            <span className="font-display text-[17px] font-semibold">Baton</span>
          </Link>
          <div className="ml-6 hidden items-center gap-1 md:flex">
            {[
              ["#film", "Demo"],
              ["#features", "Features"],
              ["#how", "How it works"],
              ["#trust", "Trust"],
            ].map(([href, label]) => (
              <a key={href} href={href} className="rounded-[9px] px-3 py-2 text-sm text-muted transition hover:bg-raised hover:text-ink">
                {label}
              </a>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            {!me && (
              <Link to="/login" className="btn btn-ghost hidden sm:inline-flex">
                Sign in
              </Link>
            )}
            <Link to={primary.to} className="btn btn-primary">
              {me ? primary.label : "Get started"}
            </Link>
          </div>
        </nav>
      </header>

      {/* ---------------------------------------------------- hero */}
      <section className="relative overflow-hidden" style={{ background: "var(--hero)" }}>
        <div className="dot-grid pointer-events-none absolute inset-0 opacity-60" aria-hidden="true" />
        <div className="relative mx-auto flex max-w-[1200px] flex-col items-center px-4 pb-16 pt-16 text-center sm:px-6 sm:pt-24">
          <span className="rise inline-flex items-center gap-2 rounded-full border border-line2 bg-panel px-3.5 py-1.5 text-[13px] text-muted">
            <span className="h-2 w-2 rounded-full bg-ok" style={{ animation: "pulse-run 2s ease-out infinite" }} />
            Now with Google, Microsoft and approve-from-email
          </span>
          <h1 className="rise mt-6 max-w-[880px] font-display text-[42px] font-semibold leading-[1.05] tracking-[-0.035em] sm:text-[68px]" style={{ animationDelay: ".05s" }}>
            Your assistant, <span className="spectrum-text">already at work.</span>
          </h1>
          <p className="rise mt-5 max-w-[640px] text-[17px] leading-relaxed text-muted sm:text-lg" style={{ animationDelay: ".16s" }}>
            Ask in plain words, let it use your email, calendar and files, and watch every step, while anything risky waits for you.
          </p>
          <div className="rise mt-8 flex flex-wrap justify-center gap-3" style={{ animationDelay: ".24s" }}>
            <Link to={primary.to} className="btn btn-primary">
              {primary.label} <Icon name="arrow" size={16} />
            </Link>
            <a href="#film" className="btn btn-ghost">
              <Icon name="eye" size={16} /> Watch the demo
            </a>
          </div>
          {!me && (
            <p className="rise mt-4 text-sm text-dim" style={{ animationDelay: ".3s" }}>
              Already have an account?{" "}
              <Link to="/login" className="font-semibold text-accent-text hover:underline">
                Sign in
              </Link>
            </p>
          )}

          {/* The product itself, the way Google and Microsoft open their pages. */}
          <figure className="rise mt-14 w-full" style={{ animationDelay: ".1s" }}>
            <div className="overflow-hidden rounded-2xl border border-line bg-panel shadow-lift">
              <img className="only-light block w-full" src="/media/screens/hero-light.webp" alt="Asking for help and watching the work happen step by step" />
              <img className="only-dark block w-full" src="/media/screens/hero-dark.webp" alt="Asking for help and watching the work happen step by step" />
            </div>
          </figure>
        </div>
      </section>

      {/* ---------------------------------------------------- demo video */}
      <section id="film" className="scroll-mt-20 border-t border-line">
        <div className="mx-auto flex max-w-[1000px] flex-col items-center gap-6 px-4 py-20 text-center sm:px-6">
          <h2 className="font-display text-[32px] font-semibold tracking-[-0.02em] sm:text-[40px]">See it in a minute</h2>
          <p className="max-w-[560px] text-muted">The real product, recorded live: sign up, connect a free AI, ask for help, and put an agent on a schedule.</p>
          <div className="w-full overflow-hidden rounded-2xl border border-line bg-[#070915] shadow-lift">
            <AutoVideo
              sound
              src="/media/product-demo.mp4"
              poster="/media/product-demo.jpg"
              label="A live demo: signing up, connecting an AI, asking for help and watching helper agents work, building an agent that runs on a schedule, and the agent tree."
            />
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------- works with */}
      <section className="border-y border-line" style={{ background: "color-mix(in srgb, var(--panel) 60%, transparent)" }}>
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-center gap-x-8 gap-y-3 px-4 py-6 sm:px-6">
          <span className="text-xs font-medium uppercase tracking-[.16em] text-dim">Works with</span>
          {WORKS_WITH.map((name) => (
            <span key={name} className="font-display text-[15px] font-semibold text-muted">
              {name}
            </span>
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------- features */}
      <section id="features" className="mx-auto flex max-w-[1200px] scroll-mt-20 flex-col gap-24 px-4 py-24 sm:px-6">
        {FEATURES.map((feature, i) => (
          <article key={feature.id} className={`grid items-center gap-10 lg:grid-cols-2 ${i % 2 ? "lg:[&>*:first-child]:order-2" : ""}`}>
            <div className="flex flex-col gap-5">
              <span className="text-sm font-semibold text-accent-text">{feature.kicker}</span>
              <h2 className="font-display text-[32px] font-semibold leading-[1.12] tracking-[-0.02em] sm:text-[40px]">{feature.title}</h2>
              <p className="text-[17px] leading-relaxed text-muted">{feature.body}</p>
              <ul className="flex flex-col gap-3">
                {feature.points.map((point) => (
                  <li key={point.text} className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent-text">
                      <Icon name={point.icon} size={14} />
                    </span>
                    <span className="pt-0.5 text-[15px] leading-snug">{point.text}</span>
                  </li>
                ))}
              </ul>
            </div>
            {/* The real product, framed like a browser window. */}
            <figure className="overflow-hidden rounded-2xl border border-line bg-raised shadow-lift">
              <div className="flex items-center gap-1.5 border-b border-line bg-panel px-4 py-3" aria-hidden="true">
                <i className="h-2.5 w-2.5 rounded-full bg-line2" />
                <i className="h-2.5 w-2.5 rounded-full bg-line2" />
                <i className="h-2.5 w-2.5 rounded-full bg-line2" />
              </div>
              <div className="flex max-h-[520px] justify-center overflow-hidden p-5 sm:p-8">
                <img className={`only-light w-full rounded-xl border border-line object-cover object-top shadow-lift ${feature.id === "safety" ? "" : "max-w-[560px]"}`} src={`/media/screens/${feature.id}-light.webp`} alt={feature.alt} loading="lazy" />
                <img className={`only-dark w-full rounded-xl border border-line object-cover object-top shadow-lift ${feature.id === "safety" ? "" : "max-w-[560px]"}`} src={`/media/screens/${feature.id}-dark.webp`} alt={feature.alt} loading="lazy" />
              </div>
            </figure>
          </article>
        ))}
      </section>

      {/* ---------------------------------------------------- how it works */}
      <section id="how" className="scroll-mt-20 border-y border-line" style={{ background: "color-mix(in srgb, var(--panel) 55%, transparent)" }}>
        <div className="mx-auto max-w-[1200px] px-4 py-20 sm:px-6">
          <h2 className="text-center font-display text-[32px] font-semibold tracking-[-0.02em] sm:text-[40px]">Working in three steps</h2>
          <div className="relative mt-12 grid gap-6 md:grid-cols-3">
            {STEPS.map((step, i) => (
              <div key={step.title} className="card rise relative flex flex-col items-center gap-3 p-7 text-center" style={{ animationDelay: `${i * 0.1}s` }}>
                <span className="flex h-11 w-11 items-center justify-center rounded-full bg-accent-soft text-accent-text">
                  <Icon name={step.icon} size={20} />
                </span>
                <span className="text-xs font-medium text-dim">Step {i + 1}</span>
                <h3 className="font-display text-xl font-semibold">{step.title}</h3>
                <p className="text-[15px] leading-relaxed text-muted">{step.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------- trust */}
      <section id="trust" className="mx-auto max-w-[1200px] scroll-mt-20 px-4 py-20 sm:px-6">
        <h2 className="text-center font-display text-[32px] font-semibold tracking-[-0.02em] sm:text-[40px]">Built to be trusted with real work</h2>
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {(
            [
              ["lock", "Encrypted for you", "Your keys and tokens are sealed with your own key and can never be read back."],
              ["shield", "Capability, not hope", "A tool a helper was not given is invisible to it, whatever a prompt says."],
              ["approvals", "You decide", "Sends and invites wait for you. Approval links never act on their own."],
              ["eye", "Nothing hidden", "Every step is written to an append-only log you can replay."],
            ] as [IconName, string, string][]
          ).map(([icon, title, body]) => (
            <div key={title} className="card lift flex flex-col gap-3 p-6">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-soft text-accent-text">
                <Icon name={icon} size={18} />
              </span>
              <h3 className="font-display text-lg font-semibold">{title}</h3>
              <p className="text-[14px] leading-relaxed text-muted">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------- closing call */}
      {!me && (
        <section className="mx-auto max-w-[1200px] px-4 pb-24 sm:px-6">
          <div className="auth-aside flex flex-col items-center gap-5 rounded-3xl border border-line px-6 py-14 text-center sm:py-16">
            <h2 className="max-w-[640px] font-display text-[30px] font-semibold leading-[1.1] tracking-[-0.025em] sm:text-[40px]">
              Hand off your first task today.
            </h2>
            <p className="max-w-[520px] text-[16px] leading-relaxed text-muted">Create an account in a minute. Connect only what you want, and approve anything that matters.</p>
            <div className="flex flex-wrap justify-center gap-3">
              <Link to="/register" className="btn btn-primary">
                Create your account <Icon name="arrow" size={16} />
              </Link>
              <Link to="/login" className="btn btn-ghost">
                Sign in
              </Link>
            </div>
          </div>
        </section>
      )}

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-4 px-4 py-8 text-[13px] text-dim sm:px-6">
          <BrandMark size={24} />
          <span>Baton</span>
          <span className="ml-auto">For students, professionals and developers.</span>
        </div>
      </footer>
    </div>
  );
}
