import type { CSSProperties, ReactNode } from "react";

/**
 * The scenes of the product film.
 *
 * Each visual is laid out in a fixed 740 x 600 box (the stage scales it),
 * and every movement is a CSS animation whose delay is counted from the
 * moment its scene starts. Nothing uses timers, which is what lets the
 * recorder seek to any exact frame.
 */

const EASE = "cubic-bezier(.16,1,.3,1)";

/** One animation: name, delay and duration in ms. */
export function s(
  name: string,
  delay: number,
  dur = 700,
  ease = EASE,
  iterations: number | "infinite" = 1,
  fill: "both" | "forwards" = "both",
): string {
  return `${name} ${dur}ms ${ease} ${delay}ms ${iterations} ${fill}`;
}

/** A second animation on an element that already animates the same
 * property must not fill backwards, or its start state would show
 * through the first animation before its own delay is up. */
const then = (name: string, delay: number, dur = 600, ease = EASE) => s(name, delay, dur, ease, 1, "forwards");

const A = (...parts: string[]): CSSProperties => ({ animation: parts.join(", ") });
const loop = (name: string, dur: number, delay = 0, ease = "linear") => s(name, delay, dur, ease, "infinite");

// ---------------------------------------------------------------- pieces

type Tone = "run" | "ok" | "ask" | "bad" | "brand" | "mute";

function Chip({ tone, children, style, dot = true }: { tone: Tone; children: ReactNode; style?: CSSProperties; dot?: boolean }) {
  return (
    <span className={`f-chip f-chip-${tone}`} style={style}>
      {dot && <i />}
      {children}
    </span>
  );
}

const AVATAR: Record<string, string> = {
  R: "linear-gradient(135deg,#ff9a5a,#ff5f7e)",
  K: "linear-gradient(135deg,#a48bff,#7b93ff)",
  M: "linear-gradient(135deg,#6ad3c4,#3cc8d8)",
  P: "linear-gradient(135deg,#ffcf6a,#ff8a4c)",
};

function Avatar({ letter, size = 44, style }: { letter: string; size?: number; style?: CSSProperties }) {
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: size * 0.3,
        background: AVATAR[letter] ?? AVATAR.K,
        color: "#0f1430",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "Outfit, sans-serif",
        fontWeight: 700,
        fontSize: size * 0.42,
        flexShrink: 0,
        ...style,
      }}
    >
      {letter}
    </span>
  );
}

/** Text that types itself out. */
function Typed({ text, delay, dur, style, className = "" }: { text: string; delay: number; dur?: number; style?: CSSProperties; className?: string }) {
  const d = dur ?? Math.max(500, text.length * 38);
  return (
    <span className={className} style={{ display: "inline-block", ...A(s("f-type", delay, d, `steps(${Math.max(4, text.length)})`)), ...style }}>
      {text}
    </span>
  );
}

function Check({ size = 14, color = "currentColor" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12l4 4 10-10" />
    </svg>
  );
}

function Spinner({ size = 14, color = "var(--run)" }: { size?: number; color?: string }) {
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: 999,
        border: `2px solid ${color}`,
        borderRightColor: "transparent",
        display: "inline-block",
        ...A(loop("f-spin", 900)),
      }}
    />
  );
}

/** A pointer that glides from one point to another and clicks. */
function Cursor({ from, to, delay, dur = 1000, click }: { from: [number, number]; to: [number, number]; delay: number; dur?: number; click?: number }) {
  const vars = { "--x0": `${from[0]}px`, "--y0": `${from[1]}px`, "--x1": `${to[0]}px`, "--y1": `${to[1]}px` } as CSSProperties;
  return (
    <>
      <div style={{ position: "absolute", left: 0, top: 0, zIndex: 30, ...vars, ...A(s("f-fade", delay - 250, 250), s("f-cursor", delay, dur, "cubic-bezier(.65,0,.35,1)"), ...(click !== undefined ? [then("f-fade-out", click + 700, 400)] : [])) }}>
        <svg width="26" height="26" viewBox="0 0 24 24" style={{ filter: "drop-shadow(0 4px 8px rgba(0,0,0,.6))" }}>
          <path d="M4 3l7 17 2.5-7.2L21 10z" fill="#fff" stroke="#0a0c18" strokeWidth="1.4" strokeLinejoin="round" />
        </svg>
      </div>
      {click !== undefined && (
        <span
          style={{
            position: "absolute",
            left: to[0] + 6,
            top: to[1] + 6,
            width: 44,
            height: 44,
            borderRadius: 999,
            border: "2px solid #fff",
            zIndex: 29,
            ...A(s("f-ripple", click, 650, "ease-out")),
          }}
        />
      )}
    </>
  );
}

function Burst({ x, y, at, color = "var(--ok)" }: { x: number; y: number; at: number; color?: string }) {
  return (
    <>
      {Array.from({ length: 10 }, (_, i) => (
        <span
          key={i}
          style={{
            position: "absolute",
            left: x,
            top: y,
            width: 7,
            height: 7,
            borderRadius: 999,
            background: i % 3 === 0 ? "var(--spark)" : color,
            ["--r" as string]: `${i * 36}deg`,
            ...A(s("f-burst", at, 800, "cubic-bezier(.2,.8,.2,1)")),
          }}
        />
      ))}
    </>
  );
}

function Switch({ onAt }: { onAt: number }) {
  return (
    <span style={{ width: 48, height: 26, borderRadius: 999, padding: 3, display: "inline-flex", ...A(s("f-track-on", onAt, 350)) }}>
      <span style={{ width: 20, height: 20, borderRadius: 999, background: "#fff", ...A(s("f-knob", onAt, 350)) }} />
    </span>
  );
}

/** Swap one thing for another at a moment in the scene. */
function Swap({ at, before, after, style }: { at: number; before: ReactNode; after: ReactNode; style?: CSSProperties }) {
  return (
    <span style={{ position: "relative", display: "inline-grid", ...style }}>
      <span style={{ gridArea: "1/1", ...A(s("f-fade-out", at, 250)) }}>{before}</span>
      <span style={{ gridArea: "1/1", ...A(s("f-pop", at + 150, 450)) }}>{after}</span>
    </span>
  );
}

const label: CSSProperties = { fontSize: 13, color: "var(--dim)", fontWeight: 500, letterSpacing: ".02em" };
const field: CSSProperties = {
  background: "var(--raised)",
  border: "1px solid var(--line)",
  borderRadius: 12,
  padding: "11px 14px",
  fontSize: 16,
  minHeight: 44,
};

// ---------------------------------------------------------------- 1. intro

function IntroVisual() {
  return (
    <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center" }}>
      <div style={{ position: "relative", width: 112, height: 112, marginBottom: 34, ...A(s("f-pop", 250, 800)) }}>
        <span style={{ position: "absolute", inset: 0, borderRadius: 32, background: "linear-gradient(135deg,#7b93ff,#a48bff 55%,#ff8a4c)", boxShadow: "0 30px 90px -20px rgba(123,147,255,.7)" }} />
        <span style={{ position: "absolute", inset: 34, borderRadius: 12, background: "#0a0c18" }} />
        <span style={{ position: "absolute", right: -6, top: -6, width: 22, height: 22, borderRadius: 999, background: "var(--spark)", boxShadow: "0 0 30px var(--spark)", ...A(s("f-pop", 900, 500), loop("f-pulse", 2000, 1400, "ease-out")) }} />
      </div>
      <div className="f-display" style={{ fontSize: 30, fontWeight: 600, color: "var(--muted)", ...A(s("f-rise", 600)) }}>
        Baton
      </div>
      <h1 className="f-display" style={{ margin: "14px 0 0", fontSize: 92, lineHeight: 1.02, fontWeight: 700 }}>
        <span style={{ display: "block", ...A(s("f-rise", 900, 900)) }}>Your assistant,</span>
        <span className="f-spectrum" style={{ display: "block", ...A(s("f-rise", 1200, 900)) }}>
          already at work.
        </span>
      </h1>
      <p style={{ marginTop: 28, fontSize: 24, color: "var(--muted)", ...A(s("f-fade", 2000, 900)) }}>
        Ask in plain words. Give it your tools. Stay in control.
      </p>
      {(
        [
          ["Assistant · running", "run", 140, 160, 2600],
          ["Specialist · done", "ok", 1010, 210, 2800],
          ["Needs you", "ask", 1010, 620, 3000],
          ["Remembers what you teach it", "brand", 120, 630, 3200],
        ] as [string, Tone, number, number, number][]
      ).map(([text, tone, x, y, at], i) => (
        <div key={text} style={{ position: "absolute", left: x, top: y, ...A(s("f-pop", at, 600)) }}>
          <div style={A(loop("f-float", 4200 + i * 500, at, "ease-in-out"))}>
            <Chip tone={tone} style={{ fontSize: 16, padding: "8px 16px", boxShadow: "0 20px 50px -20px rgba(0,0,0,.8)" }}>
              {text}
            </Chip>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- 2. set up

function SetupVisual() {
  const tools: [string, Tone][] = [
    ["gmail_search", "mute"],
    ["google_calendar_list", "mute"],
    ["run_query", "mute"],
    ["recall", "mute"],
    ["gmail_send · asks first", "ask"],
    ["delegate_to_specialist", "brand"],
  ];
  return (
    <div className="f-card" style={{ position: "absolute", left: 70, top: 30, width: 600, padding: 30, display: "flex", flexDirection: "column", gap: 20, ...A(s("f-slide-up", 150, 900)) }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <Avatar letter="R" size={60} style={A(s("f-pop", 500, 600))} />
        <div style={{ flex: 1 }}>
          <div className="f-display" style={{ fontSize: 28, fontWeight: 600 }}>
            <Typed text="Ravi" delay={700} dur={400} />
          </div>
          <div style={{ color: "var(--muted)", fontSize: 16, ...A(s("f-fade", 1100)) }}>Incident helper</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, ...A(s("f-fade", 1000)) }}>
          <Swap at={6100} before={<Chip tone="brand">draft</Chip>} after={<Chip tone="ok">active</Chip>} />
          <Switch onAt={5900} />
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8, ...A(s("f-rise", 1300)) }}>
        <span style={label}>1 · What should it do?</span>
        <div style={field}>
          <Typed text="Investigate incidents and brief me." delay={1600} dur={1300} />
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, ...A(s("f-rise", 2600)) }}>
        <span style={label}>2 · What must it never do?</span>
        <div style={field}>
          <Typed text="Never send an email without asking me." delay={2900} dur={1300} />
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10, ...A(s("f-rise", 4000)) }}>
        <span style={label}>3 · Which tools may it use?</span>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {tools.map(([t, tone], i) => (
            <Chip key={t} tone={tone} style={{ fontFamily: "Geist Mono, monospace", fontSize: 13, ...A(s("f-pop", 4300 + i * 180, 500)) }}>
              {t}
            </Chip>
          ))}
        </div>
      </div>
      <Burst x={560} y={62} at={6150} />
    </div>
  );
}

// ---------------------------------------------------------------- 3. assign

function AssignVisual() {
  const events: [string, string, Tone, ReactNode][] = [
    ["thinking", "Plans the investigation", "run", <Spinner key="s" />],
    ["recall", "“ERR_4021 means the payment vendor timed out”", "brand", <Check key="c" />],
    ["run_query", "SELECT count(*) FROM checkouts WHERE …", "ok", <Check key="c" />],
    ["get_webpage", "status.vendor.com/history", "ok", <Check key="c" />],
    ["delegate", "→ Kiran: break failures down by hour", "brand", <Check key="c" />],
  ];
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div className="f-card" style={{ position: "absolute", left: 20, top: 20, width: 700, padding: 14, display: "flex", alignItems: "center", gap: 12, ...A(s("f-fall", 150, 800)) }}>
        <Avatar letter="R" size={40} />
        <div style={{ ...field, flex: 1, minHeight: 46, display: "flex", alignItems: "center", fontSize: 16 }}>
          <Typed text="Why did checkouts fail overnight? Email me a summary." delay={500} dur={2000} />
        </div>
        <span
          style={{
            padding: "12px 20px",
            borderRadius: 12,
            fontWeight: 600,
            color: "#0a0c18",
            background: "linear-gradient(135deg,#7b93ff,#a48bff)",
            ...A(s("f-press", 2700, 350)),
          }}
        >
          Assign
        </span>
      </div>
      <Cursor from={[520, 300]} to={[650, 30]} delay={1900} dur={700} click={2700} />

      <div className="f-card" style={{ position: "absolute", left: 20, top: 120, width: 700, padding: 22, display: "flex", flexDirection: "column", gap: 14, ...A(s("f-slide-up", 3000, 800)) }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ width: 10, height: 10, borderRadius: 999, background: "var(--run)", ...A(loop("f-pulse", 1600, 3200, "ease-out")) }} />
          <span className="f-display" style={{ fontSize: 19, fontWeight: 600, flex: 1 }}>
            Checkout failures overnight
          </span>
          <Chip tone="run">running</Chip>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {events.map(([tool, text, tone, icon], i) => (
            <div
              key={tool}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "10px 12px",
                borderRadius: 12,
                background: "var(--raised)",
                border: "1px solid var(--line)",
                ...A(s("f-slide-left", 3500 + i * 650, 600)),
              }}
            >
              <span className="f-mono" style={{ width: 104, fontSize: 13, color: tone === "brand" ? "var(--accent-text)" : tone === "ok" ? "var(--ok-text)" : "var(--run-text)" }}>
                {tool}
              </span>
              <span style={{ flex: 1, fontSize: 14, color: "var(--muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{text}</span>
              <span style={{ color: "var(--ok)", display: "inline-flex" }}>{icon}</span>
            </div>
          ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14, fontSize: 13, color: "var(--dim)", ...A(s("f-fade", 3400)) }}>
          <span className="f-mono">tokens</span>
          <span style={{ flex: 1, height: 6, borderRadius: 999, background: "var(--raised)", overflow: "hidden" }}>
            <span style={{ display: "block", height: "100%", width: "62%", transformOrigin: "left", background: "linear-gradient(90deg,#3cc8d8,#7b93ff)", ...A(s("f-grow-x", 3400, 4800, "linear")) }} />
          </span>
          <span className="f-mono">step 5 of 20</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- 4. tree

function TreeNode({ x, y, letter, name, role, at, status }: { x: number; y: number; letter: string; name: string; role: string; at: number; status: ReactNode }) {
  return (
    <div className="f-card" style={{ position: "absolute", left: x - 125, top: y - 46, width: 250, padding: "14px 16px", display: "flex", alignItems: "center", gap: 12, borderRadius: 18, ...A(s("f-pop", at, 650)) }}>
      <Avatar letter={letter} size={44} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="f-display" style={{ fontWeight: 600, fontSize: 18 }}>{name}</div>
        <div style={{ fontSize: 13, color: "var(--dim)" }}>{role}</div>
      </div>
      {status}
    </div>
  );
}

function TreeVisual() {
  const paths = ["M370 156 C370 260, 170 250, 170 334", "M370 156 C370 260, 570 250, 570 334"];
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <svg width="740" height="600" style={{ position: "absolute", inset: 0 }}>
        <defs>
          <linearGradient id="f-tree" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#7b93ff" />
            <stop offset="1" stopColor="#a48bff" />
          </linearGradient>
        </defs>
        {paths.map((d, i) => (
          <g key={d}>
            <path d={d} fill="none" stroke="url(#f-tree)" strokeWidth={2.5} strokeDasharray={400} style={{ ["--len" as string]: 400, ...A(s("f-draw", 1100 + i * 200, 900, "ease-out")) }} />
            <path d={d} fill="none" stroke="#fff" strokeOpacity={0.85} strokeWidth={2.5} strokeDasharray="5 15" strokeLinecap="round" style={A(s("f-fade", 2000 + i * 200, 400), loop("f-flow", 900, 2000))} />
          </g>
        ))}
      </svg>
      <TreeNode x={370} y={110} letter="R" name="Ravi" role="Lead helper" at={300} status={<Chip tone="run">running</Chip>} />
      <TreeNode
        x={170}
        y={380}
        letter="K"
        name="Kiran"
        role="Data specialist"
        at={1800}
        status={<Swap at={4600} before={<Chip tone="run">working</Chip>} after={<Chip tone="ok">done</Chip>} />}
      />
      <TreeNode
        x={570}
        y={380}
        letter="M"
        name="Meera"
        role="Comms specialist"
        at={2000}
        status={
          <Swap
            at={5400}
            before={<Chip tone="run">working</Chip>}
            after={
              <span style={{ borderRadius: 999, ...A(loop("f-pulse", 1600, 5600, "ease-out")), ["--pulse" as string]: "rgba(255,181,71,.6)" }}>
                <Chip tone="ask">asks first</Chip>
              </span>
            }
          />
        }
      />
      <div className="f-card" style={{ position: "absolute", left: 40, top: 470, width: 660, padding: "14px 18px", display: "flex", gap: 12, alignItems: "center", fontSize: 15, ...A(s("f-slide-up", 6200, 700)) }}>
        <span style={{ color: "var(--ok)", display: "inline-flex" }}>
          <Check size={18} />
        </span>
        <span style={{ color: "var(--muted)" }}>
          <b style={{ color: "var(--text)" }}>Kiran:</b> 1,284 failed checkouts, all ERR_4021, between 01:10 and 02:40.
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- 5. approval

function ApprovalVisual() {
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div className="f-card" style={{ position: "absolute", left: 0, top: 40, width: 420, padding: 22, display: "flex", flexDirection: "column", gap: 14, ...A(s("f-slide-right", 150, 800)) }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Avatar letter="R" size={36} />
          <span className="f-display" style={{ fontWeight: 600, fontSize: 18, flex: 1 }}>Ravi wants to send</span>
          <Swap
            at={5700}
            before={
              <span style={{ borderRadius: 999, ["--pulse" as string]: "rgba(255,181,71,.6)", ...A(loop("f-pulse", 1600, 600, "ease-out")) }}>
                <Chip tone="ask">paused</Chip>
              </span>
            }
            after={<Swap at={7300} before={<Chip tone="run">resuming</Chip>} after={<Chip tone="ok">completed</Chip>} />}
          />
        </div>
        <div style={{ borderRadius: 14, background: "var(--raised)", border: "1px solid var(--line)", padding: 16, display: "flex", flexDirection: "column", gap: 10, fontSize: 15 }}>
          {(
            [
              ["tool", "gmail_send · destructive"],
              ["to", "priya@example.com"],
              ["subject", "Checkout incident summary"],
              ["body", "1,284 checkouts failed overnight when the payment vendor timed out. Retries are now on."],
            ] as [string, string][]
          ).map(([k, v], i) => (
            <div key={k} style={A(s("f-rise", 700 + i * 250, 600))}>
              <div className="f-mono" style={{ fontSize: 12, color: "var(--dim)" }}>{k}</div>
              <div style={{ color: k === "tool" ? "var(--bad)" : "var(--text)", lineHeight: 1.45 }}>{v}</div>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 13, color: "var(--dim)", ...A(s("f-fade", 1800)) }}>
          <Swap at={5700} before={<span>Waiting for you · expires in 24 h</span>} after={<span style={{ color: "var(--ok-text)" }}>Approved by you from your inbox</span>} />
        </div>
      </div>

      {/* The phone */}
      <div style={{ position: "absolute", left: 460, top: 0, width: 270, height: 560, borderRadius: 42, padding: 10, background: "linear-gradient(160deg,#2a3156,#12162a)", boxShadow: "0 40px 100px -30px rgba(0,0,0,.9)", ...A(s("f-slide-left", 2100, 900)) }}>
        <div style={{ position: "relative", width: "100%", height: "100%", borderRadius: 34, background: "#070912", overflow: "hidden", padding: "40px 14px 14px" }}>
          <div style={{ position: "absolute", top: 12, left: "50%", width: 80, height: 22, marginLeft: -40, borderRadius: 999, background: "#000" }} />
          <div className="f-mono" style={{ textAlign: "center", fontSize: 34, color: "#cfd5f5", fontWeight: 300 }}>09:41</div>
          <div style={{ marginTop: 18, borderRadius: 18, background: "rgba(40,46,80,.85)", padding: 14, display: "flex", flexDirection: "column", gap: 10, ...A(s("f-fall", 2900, 700)) }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--dim)" }}>
              <span style={{ width: 20, height: 20, borderRadius: 6, background: "linear-gradient(135deg,#7b93ff,#ff8a4c)" }} />
              Mail · now
            </div>
            <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.3 }}>Approval needed: Ravi wants to gmail send</div>
            <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.4 }}>To priya@example.com · “Checkout incident summary”</div>
            <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
              <span style={{ flex: 1, textAlign: "center", padding: "9px 0", borderRadius: 10, fontSize: 13, fontWeight: 600, position: "relative", overflow: "hidden" }}>
                <span style={{ position: "absolute", inset: 0, background: "#2b4ee0" }} />
                <span style={{ position: "absolute", inset: 0, background: "var(--ok)", ...A(s("f-fade", 5350, 250)) }} />
                <span style={{ position: "relative", display: "inline-flex", alignItems: "center", gap: 5, color: "#fff", ...A(s("f-press", 5200, 300)) }}>
                  <Swap at={5350} before={<span>Approve</span>} after={<span style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "#06180e" }}><Check size={13} /> Approved</span>} />
                </span>
              </span>
              <span style={{ flex: 1, textAlign: "center", padding: "9px 0", borderRadius: 10, fontSize: 13, fontWeight: 600, background: "rgba(240,106,128,.18)", color: "var(--bad)" }}>Reject</span>
            </div>
          </div>
          <div style={{ marginTop: 10, borderRadius: 18, background: "rgba(40,46,80,.6)", padding: 12, display: "flex", gap: 10, alignItems: "center", fontSize: 12, color: "var(--muted)", ...A(s("f-fall", 3500, 700)) }}>
            <span style={{ width: 20, height: 20, borderRadius: 6, background: "linear-gradient(135deg,#36C5F0,#2EB67D,#ECB22E,#E01E5A)" }} />
            <span>
              <b style={{ color: "var(--text)" }}>#ops</b> · Approval needed
            </span>
          </div>
        </div>
      </div>
      <Cursor from={[700, 520]} to={[530, 214]} delay={4200} dur={900} click={5200} />
      <Burst x={420} y={60} at={7400} />
    </div>
  );
}

// ---------------------------------------------------------------- 6. connect

function BrandTile({ kind, size = 56 }: { kind: "google" | "microsoft"; size?: number }) {
  const gradient = kind === "google" ? "linear-gradient(135deg,#4285F4,#34A853 55%,#FBBC05 80%,#EA4335)" : "linear-gradient(135deg,#F25022,#7FBA00 40%,#00A4EF 70%,#FFB900)";
  return (
    <span style={{ width: size, height: size, borderRadius: size * 0.28, padding: 2, background: gradient, display: "inline-flex", flexShrink: 0 }}>
      <span className="f-display" style={{ flex: 1, borderRadius: size * 0.24, background: "var(--panel)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: size * 0.42 }}>
        {kind === "google" ? "G" : "M"}
      </span>
    </span>
  );
}

function ConnectVisual() {
  const apps = ["Gmail", "Calendar", "Drive"];
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      {(["google", "microsoft"] as const).map((kind, i) => (
        <div key={kind} className="f-card" style={{ position: "absolute", left: i * 375, top: 20, width: 355, padding: 20, display: "flex", flexDirection: "column", gap: 14, ...A(s("f-rise", 200 + i * 200, 800)) }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <BrandTile kind={kind} />
            <div>
              <div className="f-display" style={{ fontSize: 20, fontWeight: 600 }}>{kind === "google" ? "Google Workspace" : "Microsoft 365"}</div>
              <div style={{ fontSize: 13, color: "var(--dim)" }}>{kind === "google" ? "Gmail · Calendar · Drive" : "Outlook · Calendar · OneDrive"}</div>
            </div>
          </div>
          <Swap
            at={kind === "google" ? 4300 : 5900}
            style={{ justifyItems: "start" }}
            before={
              <span style={{ padding: "9px 16px", borderRadius: 11, fontWeight: 600, fontSize: 14, color: "#0a0c18", background: "linear-gradient(135deg,#7b93ff,#a48bff)", display: "inline-block", ...(kind === "google" ? A(s("f-press", 1500, 300)) : {}) }}>
                Connect
              </span>
            }
            after={
              <span style={{ display: "inline-flex", alignItems: "center", gap: 10, fontSize: 14 }}>
                <span style={{ width: 9, height: 9, borderRadius: 999, background: "var(--ok)", ["--pulse" as string]: "rgba(95,208,143,.6)", ...A(loop("f-pulse", 1700, 4500, "ease-out")) }} />
                {kind === "google" ? "ops@victopia.com" : "ops@victopia.onmicrosoft.com"}
                <Chip tone="ok">connected</Chip>
              </span>
            }
          />
        </div>
      ))}
      <Cursor from={[330, 360]} to={[60, 118]} delay={700} dur={800} click={1500} />

      {/* consent sheet */}
      <div className="f-card" style={{ position: "absolute", left: 170, top: 150, width: 400, padding: 22, zIndex: 20, display: "flex", flexDirection: "column", gap: 12, ...A(s("f-slide-up", 1800, 600), then("f-slide-away", 3900, 450)) }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <BrandTile kind="google" size={34} />
          <span style={{ fontWeight: 600 }}>Baton wants to</span>
        </div>
        {["Read, draft and send mail", "See and create calendar events", "Read Drive files (read-only)"].map((t, i) => (
          <div key={t} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14, color: "var(--muted)", ...A(s("f-rise", 2100 + i * 300, 500)) }}>
            <span style={{ width: 20, height: 20, borderRadius: 6, background: "var(--ok-soft)", color: "var(--ok)", display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
              <Check size={12} />
            </span>
            {t}
          </div>
        ))}
        <span style={{ alignSelf: "flex-end", padding: "8px 18px", borderRadius: 10, background: "#2b4ee0", color: "#fff", fontWeight: 600, fontSize: 14, ...A(s("f-press", 3500, 300)) }}>Allow</span>
      </div>

      {/* what Ravi can now reach */}
      <div style={{ position: "absolute", left: 0, top: 300, width: 740, height: 280 }}>
        {apps.map((app, i) => (
          <div key={app} className="f-card" style={{ position: "absolute", left: 40 + i * 240, top: 0, width: 180, padding: "12px 14px", borderRadius: 14, display: "flex", alignItems: "center", gap: 10, ...A(s("f-pop", 4600 + i * 200, 550)) }}>
            <span style={{ width: 30, height: 30, borderRadius: 9, background: "var(--accent-soft)", color: "var(--accent-text)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 14 }}>
              {app.charAt(0)}
            </span>
            <span style={{ fontWeight: 500 }}>{app}</span>
          </div>
        ))}
        {apps.map((app, i) => {
          const x = 130 + i * 240;
          const left = Math.min(x, 370);
          const width = Math.max(Math.abs(370 - x), 2);
          return (
            <div key={`${app}-beam`} style={{ position: "absolute", left, top: 62, width, height: 120, ...A(s("f-fade", 5200, 400)) }}>
              <svg width={width} height={120} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
                <path
                  d={x < 370 ? `M0 0 C0 70, ${width} 50, ${width} 120` : x > 370 ? `M${width} 0 C${width} 70, 0 50, 0 120` : "M1 0 L1 120"}
                  fill="none"
                  stroke="var(--accent)"
                  strokeOpacity={0.8}
                  strokeWidth={2}
                  strokeDasharray="5 12"
                  style={A(loop("f-flow", 800, 5200))}
                />
              </svg>
            </div>
          );
        })}
        <div style={{ position: "absolute", left: 270, top: 186, width: 200, display: "flex", alignItems: "center", gap: 12, justifyContent: "center", ...A(s("f-pop", 5000, 600)) }}>
          <Avatar letter="R" size={52} />
          <div>
            <div className="f-display" style={{ fontWeight: 600, fontSize: 18 }}>Ravi</div>
            <div style={{ fontSize: 13, color: "var(--ok-text)" }}>8 new tools</div>
          </div>
        </div>
      </div>
      <div style={{ position: "absolute", left: 0, top: 560, width: 740, textAlign: "center", fontSize: 14, color: "var(--dim)", ...A(s("f-fade", 6300)) }}>
        Tokens are encrypted with your own key and never enter the prompt.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- 7. memory + keys

function MemoryVisual() {
  const memories = [
    { text: "ERR_4021 at checkout means the payment vendor timed out. Retry once, then hand to a human.", match: true },
    { text: "I want incident summaries before 9am, in three bullet points.", match: false },
    { text: "Vendor maintenance runs 01:00–03:00 UTC on the first Tuesday.", match: false },
  ];
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div className="f-card" style={{ position: "absolute", left: 0, top: 40, width: 420, padding: 20, display: "flex", flexDirection: "column", gap: 12, ...A(s("f-slide-right", 150, 800)) }}>
        <div className="f-display" style={{ fontSize: 19, fontWeight: 600 }}>Your memory</div>
        <div style={{ ...field, display: "flex", alignItems: "center", gap: 10 }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--dim)" strokeWidth={2}>
            <path d="M11 5a6 6 0 1 1 0 12 6 6 0 0 1 0-12zM20 20l-4.5-4.5" />
          </svg>
          <Typed text="why do checkouts time out?" delay={600} dur={1100} />
        </div>
        {memories.map((m, i) => (
          <div
            key={m.text}
            style={{
              borderRadius: 14,
              border: "1px solid var(--line)",
              background: "var(--raised)",
              padding: "12px 14px",
              fontSize: 14,
              lineHeight: 1.45,
              color: m.match ? "var(--text)" : "var(--muted)",
              ...A(s("f-rise", 1500 + i * 220, 600), m.match ? s("f-glow-ring", 2700, 600) : then("f-dim", 2700, 600, "ease")),
            }}
          >
            {m.text}
            {m.match && (
              <div style={{ marginTop: 8, display: "flex", gap: 8, ...A(s("f-fade", 2900)) }}>
                <Chip tone="brand" dot={false}>recalled</Chip>
                <Chip tone="mute" dot={false}>match 0.91</Chip>
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="f-card" style={{ position: "absolute", left: 450, top: 110, width: 290, padding: 20, display: "flex", flexDirection: "column", gap: 14, ...A(s("f-slide-left", 3500, 800)) }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span className="f-display" style={{ width: 44, height: 44, borderRadius: 13, background: "var(--raised)", border: "1px solid var(--line2)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 700, color: "var(--accent-text)" }}>G</span>
          <div style={{ flex: 1 }}>
            <div className="f-display" style={{ fontWeight: 600, fontSize: 17 }}>Google Gemini</div>
            <div className="f-mono" style={{ fontSize: 13, color: "var(--dim)" }}>key ••••••••3f9a</div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: "var(--dim)" }}>
          <span>You</span>
          <span style={{ position: "relative", flex: 1, height: 2, borderRadius: 2, background: "linear-gradient(90deg,var(--line2),var(--ok),var(--line2))" }}>
            {[0, 800].map((d) => (
              <span key={d} style={{ position: "absolute", top: -3, width: 8, height: 8, borderRadius: 999, background: "var(--ok)", boxShadow: "0 0 10px var(--ok)", ...A(s("f-beam", 4600 + d, 1600, "ease-in-out", "infinite")) }} />
            ))}
          </span>
          <span>Gemini</span>
        </div>
        <div style={{ display: "flex", gap: 8, ...A(s("f-pop", 4400, 500)) }}>
          <Chip tone="ok">working</Chip>
          <Chip tone="mute" dot={false}>your key, your bill</Chip>
        </div>
        <div style={{ fontSize: 13, color: "var(--dim)", lineHeight: 1.45, ...A(s("f-fade", 5000)) }}>
          Encrypted with your own key. Nobody can read it back, not even us.
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- 8. outro

function OutroVisual() {
  const pillars: [string, string, string][] = [
    ["Just for you", "Your account is sealed off from everyone else", "var(--jade)"],
    ["The server sees counts", "Never your chats, memory or keys", "#a48bff"],
    ["Every step logged", "Replay any run, step by step", "var(--spark)"],
  ];
  return (
    <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", gap: 26 }}>
      <div style={{ display: "flex", gap: 18 }}>
        {pillars.map(([title, body, color], i) => (
          <div key={title} className="f-card" style={{ width: 290, padding: "18px 20px", textAlign: "left", borderTop: `3px solid ${color}`, ...A(s("f-rise", 200 + i * 200, 800)) }}>
            <div className="f-display" style={{ fontSize: 20, fontWeight: 600 }}>{title}</div>
            <div style={{ fontSize: 15, color: "var(--muted)", marginTop: 4 }}>{body}</div>
          </div>
        ))}
      </div>
      <h2 className="f-display" style={{ margin: "30px 0 0", fontSize: 76, fontWeight: 700, lineHeight: 1.05 }}>
        <span style={{ display: "block", ...A(s("f-rise", 1500, 900)) }}>Your assistant,</span>
        <span className="f-spectrum" style={{ display: "block", ...A(s("f-rise", 1800, 900)) }}>already at work.</span>
      </h2>
      <div style={{ position: "relative", overflow: "hidden", marginTop: 6, padding: "16px 34px", borderRadius: 16, fontWeight: 600, fontSize: 20, color: "#0a0c18", background: "linear-gradient(135deg,#7b93ff,#a48bff 60%,#ff8a4c)", boxShadow: "0 24px 70px -20px rgba(123,147,255,.7)", ...A(s("f-pop", 2700, 700)) }}>
        <span style={{ position: "absolute", top: 0, bottom: 0, width: 80, background: "linear-gradient(90deg,transparent,rgba(255,255,255,.55),transparent)", ...A(loop("f-sheen", 2200, 3400, "ease-in-out")) }} />
        Ask your first question →
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- catalogue

export interface Caption {
  n: string;
  kicker: string;
  title: string;
  body: string;
}

export interface SceneDef {
  id: string;
  label: string;
  duration: number;
  /** Full-bleed scenes (intro, outro) have no caption column. */
  caption?: Caption;
  Visual: () => JSX.Element;
}

export const SCENES: SceneDef[] = [
  { id: "intro", label: "Intro", duration: 6000, Visual: IntroVisual },
  {
    id: "setup",
    label: "Set up",
    duration: 8000,
    caption: { n: "01", kicker: "Set up", title: "Set up a helper in a minute", body: "Answer three plain questions and pick its tools. No prompt engineering." },
    Visual: SetupVisual,
  },
  {
    id: "assign",
    label: "Ask",
    duration: 9000,
    caption: { n: "02", kicker: "Ask", title: "Ask for help, watch every step", body: "Every thought, tool call and result streams live, and is kept for replay." },
    Visual: AssignVisual,
  },
  {
    id: "tree",
    label: "Delegate",
    duration: 9000,
    caption: { n: "03", kicker: "Delegate", title: "Your helper hands parts to specialists", body: "One level deep, on purpose: errors multiply with every hop." },
    Visual: TreeVisual,
  },
  {
    id: "approval",
    label: "Approve",
    duration: 10000,
    caption: { n: "04", kicker: "Stay in control", title: "Risky actions wait for you", body: "Approve from the app, your inbox or Slack. Opening a link never decides anything." },
    Visual: ApprovalVisual,
  },
  {
    id: "connect",
    label: "Connect",
    duration: 8000,
    caption: { n: "05", kicker: "Connect", title: "One click to Google and Microsoft", body: "Mail, calendar and files, with the narrowest permissions that still do the job." },
    Visual: ConnectVisual,
  },
  {
    id: "memory",
    label: "Remember",
    duration: 8000,
    caption: { n: "06", kicker: "Remember", title: "It learns how you work, on your own key", body: "Your memory, recalled by meaning. Bring your own model key; it is never shown again." },
    Visual: MemoryVisual,
  },
  { id: "outro", label: "Private", duration: 7000, Visual: OutroVisual },
];

export const TOTAL_MS = SCENES.reduce((sum, scene) => sum + scene.duration, 0);

export function CaptionBlock({ caption }: { caption: Caption }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, ...A(s("f-rise", 150)) }}>
        <span className="f-mono" style={{ fontSize: 15, color: "var(--spark)" }}>{caption.n}</span>
        <span style={{ width: 36, height: 2, borderRadius: 2, background: "linear-gradient(90deg,var(--accent),var(--spark))", transformOrigin: "left", ...A(s("f-grow-x", 350, 600)) }} />
        <span style={{ fontSize: 15, letterSpacing: ".16em", textTransform: "uppercase", color: "var(--accent-text)", fontWeight: 600 }}>{caption.kicker}</span>
      </div>
      <h2 className="f-display" style={{ margin: 0, fontSize: 46, lineHeight: 1.08, fontWeight: 700, ...A(s("f-rise", 300, 800)) }}>
        {caption.title}
      </h2>
      <p style={{ margin: 0, fontSize: 19, lineHeight: 1.5, color: "var(--muted)", ...A(s("f-rise", 500, 800)) }}>{caption.body}</p>
    </div>
  );
}
