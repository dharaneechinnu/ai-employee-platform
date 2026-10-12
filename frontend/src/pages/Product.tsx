import { Link } from "react-router-dom";
import { AutoVideo } from "../components/AutoVideo";
import { Film } from "../components/film/Film";
import { Icon, type IconName } from "../components/icons";
import { BrandMark } from "../components/Layout";
import { ThemeToggle } from "../components/ui";
import { useAuth } from "../lib/auth";

/**
 * The public product overview: what AI Employees is, in one film and
 * four features. Each feature is shown by its own scene from the film,
 * looping beside the words, so the page and the video never disagree.
 */

interface Feature {
  id: string;
  scene: string;
  kicker: string;
  title: string;
  body: string;
  points: { icon: IconName; text: string }[];
}

const FEATURES: Feature[] = [
  {
    id: "live",
    scene: "assign",
    kicker: "Assign and watch",
    title: "Give it the work. Watch every step.",
    body: "Hire an AI Employee by answering three plain questions, then assign a task the way you would to a colleague. Every thought, tool call and result streams live.",
    points: [
      { icon: "employees", text: "Guided setup: what it does, what it must never do, when to ask" },
      { icon: "terminal", text: "A live, replayable log of every step, token and cost" },
      { icon: "tree", text: "A manager can hand parts of the job to specialists, shown as a live tree" },
    ],
  },
  {
    id: "safety",
    scene: "approval",
    kicker: "Safety and approvals",
    title: "Anything risky waits for a person.",
    body: "Each company sets what runs on its own, what asks first, and what is never allowed. A paused run waits safely, then picks up exactly where it stopped.",
    points: [
      { icon: "approvals", text: "Approve from the app, your inbox or Slack, with the full action shown" },
      { icon: "lock", text: "Reading is automatic, sending asks first, catastrophic actions are blocked for everyone" },
      { icon: "shield", text: "Keys and tokens never enter the model's prompt, so injected text cannot steal them" },
    ],
  },
  {
    id: "connect",
    scene: "connect",
    kicker: "Connected apps",
    title: "One click to the tools you already use.",
    body: "Connect Google Workspace or Microsoft 365 once, and your AI Employees can search mail, draft replies, check calendars and read files. Nothing to paste, nothing to copy.",
    points: [
      { icon: "mail", text: "Gmail and Outlook: search, read, draft, and send with approval" },
      { icon: "calendar", text: "Google Calendar and Outlook: see the week, create events" },
      { icon: "folder", text: "Drive and OneDrive, read-only by permission, not just by promise" },
    ],
  },
  {
    id: "memory",
    scene: "memory",
    kicker: "Memory, your own key, many companies",
    title: "It learns your company. You hold the keys.",
    body: "Company memory is recalled by meaning, so lessons from one run help the next. Bring your own model key; your bill stays yours. Run many companies from one platform.",
    points: [
      { icon: "memory", text: "Shared and per-employee memory, searched by meaning" },
      { icon: "providers", text: "Bring your own key: Gemini, OpenRouter and more" },
      { icon: "members", text: "Each company sealed off; platform staff see counts, never content" },
    ],
  },
];

const WORKS_WITH = ["Gmail", "Google Calendar", "Google Drive", "Outlook", "OneDrive", "Slack", "PostgreSQL", "Gemini", "OpenRouter"];

const STEPS: { icon: IconName; title: string; body: string }[] = [
  { icon: "employees", title: "Hire", body: "Describe the job in three plain answers and pick its tools." },
  { icon: "link", title: "Connect", body: "Sign in to Google or Microsoft once. Set what needs approval." },
  { icon: "tasks", title: "Assign", body: "Hand over work and watch it happen, step by step." },
];

export default function Product() {
  const { me } = useAuth();
  const primary = me ? { to: "/tasks", label: "Open your workspace" } : { to: "/login", label: "Sign in" };

  return (
    <div className="min-h-screen bg-bg text-ink">
      {/* ---------------------------------------------------- nav */}
      <header className="sticky top-0 z-30 border-b border-line backdrop-blur-xl" style={{ background: "color-mix(in srgb, var(--bg) 78%, transparent)" }}>
        <nav className="mx-auto flex max-w-[1200px] items-center gap-3 px-4 py-3 sm:px-6">
          <Link to="/" className="flex items-center gap-2.5">
            <BrandMark size={32} />
            <span className="font-display text-[17px] font-semibold">AI Employees</span>
          </Link>
          <div className="ml-6 hidden items-center gap-1 md:flex">
            {[
              ["#film", "Demo"],
              ["#features", "Features"],
              ["#how", "How it works"],
              ["#trust", "Trust"],
            ].map(([href, label]) => (
              <a key={href} href={href} className="rounded-lg px-3 py-2 text-sm text-muted transition hover:bg-raised hover:text-ink">
                {label}
              </a>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            <Link to={primary.to} className="btn btn-primary">
              {primary.label}
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
          <h1 className="rise mt-6 max-w-[920px] font-display text-[44px] font-bold leading-[1.02] tracking-tight sm:text-[72px]" style={{ animationDelay: ".08s" }}>
            Your AI team, <span className="spectrum-text">already at work.</span>
          </h1>
          <p className="rise mt-5 max-w-[640px] text-[17px] leading-relaxed text-muted sm:text-lg" style={{ animationDelay: ".16s" }}>
            Hire AI Employees, give them your email, calendar and files, and watch every step, while anything risky waits for a person.
          </p>
          <div className="rise mt-8 flex flex-wrap justify-center gap-3" style={{ animationDelay: ".24s" }}>
            <Link to={primary.to} className="btn btn-primary">
              {primary.label} <Icon name="arrow" size={16} />
            </Link>
            <a href="#film" className="btn btn-ghost">
              <Icon name="eye" size={16} /> Watch the demo
            </a>
          </div>

          <div id="film" className="rise mt-14 w-full scroll-mt-24" style={{ animationDelay: ".32s" }}>
            <div className="halo rounded-[26px] p-[1.5px]" style={{ boxShadow: "0 60px 160px -60px var(--glow)" }}>
              <div className="overflow-hidden rounded-[25px] bg-[#070915]">
                <AutoVideo
                  src="/media/product-demo.mp4"
                  poster="/media/product-demo.jpg"
                  label="A one-minute live demo: connecting Google, giving an AI Employee tools, assigning a task, watching it run and delegate, approving from email, and the finished result."
                />
              </div>
            </div>
            <p className="mt-3 text-[13px] text-dim">The real product, recorded live · under a minute</p>
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
              <span className="flex items-center gap-3 text-[13px] font-semibold uppercase tracking-[.16em] text-accent-text">
                <span className="font-mono text-spark">0{i + 1}</span>
                <span className="h-0.5 w-8 rounded bg-gradient-to-r from-accent to-spark" />
                {feature.kicker}
              </span>
              <h2 className="font-display text-[34px] font-bold leading-[1.08] tracking-tight sm:text-[42px]">{feature.title}</h2>
              <p className="text-[17px] leading-relaxed text-muted">{feature.body}</p>
              <ul className="flex flex-col gap-3">
                {feature.points.map((point) => (
                  <li key={point.text} className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-accent-soft text-accent-text">
                      <Icon name={point.icon} size={16} />
                    </span>
                    <span className="pt-1 text-[15px] leading-snug">{point.text}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="card lift overflow-hidden rounded-[24px] p-0">
              <Film only={feature.scene} />
            </div>
          </article>
        ))}
      </section>

      {/* ---------------------------------------------------- how it works */}
      <section id="how" className="scroll-mt-20 border-y border-line" style={{ background: "color-mix(in srgb, var(--panel) 55%, transparent)" }}>
        <div className="mx-auto max-w-[1200px] px-4 py-20 sm:px-6">
          <h2 className="text-center font-display text-[34px] font-bold tracking-tight sm:text-[42px]">Working in three steps</h2>
          <div className="relative mt-12 grid gap-6 md:grid-cols-3">
            <div className="flow-line pointer-events-none absolute left-[16%] right-[16%] top-9 hidden h-0.5 md:block" aria-hidden="true" />
            {STEPS.map((step, i) => (
              <div key={step.title} className="card rise relative flex flex-col items-center gap-3 p-7 text-center" style={{ animationDelay: `${i * 0.1}s` }}>
                <span className="flex h-12 w-12 items-center justify-center rounded-2xl text-accent-on" style={{ background: "linear-gradient(135deg,var(--accent),var(--accent2))" }}>
                  <Icon name={step.icon} size={22} />
                </span>
                <span className="font-mono text-xs text-dim">step {i + 1}</span>
                <h3 className="font-display text-xl font-semibold">{step.title}</h3>
                <p className="text-[15px] leading-relaxed text-muted">{step.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------- trust */}
      <section id="trust" className="mx-auto max-w-[1200px] scroll-mt-20 px-4 py-20 sm:px-6">
        <h2 className="text-center font-display text-[34px] font-bold tracking-tight sm:text-[42px]">Built to be trusted with real work</h2>
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {(
            [
              ["lock", "Encrypted per company", "Keys and tokens are sealed with each company's own key and can never be read back."],
              ["shield", "Capability, not hope", "A tool an employee was not given is invisible to it, whatever a prompt says."],
              ["approvals", "Humans decide", "Sends and invites wait for a person. Approval links never act on their own."],
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

      {/* ---------------------------------------------------- call to action */}
      <section className="px-4 pb-20 sm:px-6">
        <div className="halo mx-auto max-w-[1200px] rounded-[28px] p-[1.5px]">
          <div className="relative flex flex-col items-center gap-5 overflow-hidden rounded-[27px] bg-panel px-6 py-16 text-center" style={{ background: "var(--hero), var(--panel)" }}>
            <h2 className="max-w-[720px] font-display text-[34px] font-bold leading-tight tracking-tight sm:text-[48px]">
              Put your first AI Employee <span className="spectrum-text">to work today.</span>
            </h2>
            <p className="max-w-[520px] text-muted">Accounts are by invitation. Ask your company admin for a link, or sign in if you have one.</p>
            <Link to={primary.to} className="btn btn-primary">
              {primary.label} <Icon name="arrow" size={16} />
            </Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-4 px-4 py-8 text-[13px] text-dim sm:px-6">
          <BrandMark size={24} />
          <span>AI Employees</span>
          <span className="ml-auto">Your AI team, already at work.</span>
        </div>
      </footer>
    </div>
  );
}
