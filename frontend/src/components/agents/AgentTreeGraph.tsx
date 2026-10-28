import { useEffect, useMemo, useRef } from "react";
import type { Agent } from "../../lib/api";
import { flowFor, type Flow } from "../../lib/agentFlows";
import { toolLabel } from "../../lib/labels";
import type { NodeLive } from "../../lib/liveTree";
import { Icon } from "../icons";
import { ServiceMark, serviceForTool } from "../ServiceMark";
import { relativeTime } from "../ui";
import AgentAvatar from "./AgentAvatar";
import type { PanelNode } from "./RunPanel";

/**
 * One agent as a tree, read left to right: what starts it (you asking,
 * its schedule, or the lead handing it work), the agent, the stages it
 * goes through, the tools under each stage with the real app's logo,
 * and what it gives back. Dots run along the lines in that order, so
 * the picture says what happens without reading a word. Tools the last
 * run used are ticked.
 */

const TRIG = { x: 0, w: 196, h: 66 };
const AGENT = { x: 232, w: 216, h: 80 };
const STAGE = { x: 484, w: 214, h: 64 };
const TOOL = { x: 734, w: 224, h: 38, step: 46 };
const OUT = { x: 994, w: 216, h: 92 };
const WIDTH = OUT.x + OUT.w;
const GAP = 18;
const CYCLE = 3.6;

interface Trigger {
  id: string;
  title: string;
  note: string;
  role: string;
  primary: boolean;
}

interface Placed {
  stages: { title: string; detail: string; icon: Flow["steps"][number]["icon"]; asks: boolean; y: number; tools: { name: string; y: number }[]; helpers: string[] }[];
  triggers: (Trigger & { y: number })[];
  agentY: number;
  outY: number;
  height: number;
}

function triggersFor(node: PanelNode, agents: Agent[]): Trigger[] {
  if (node.kind === "helper") {
    return [{ id: "lead", title: "Lead assistant", note: "Hands it part of a job", role: "lead", primary: true }];
  }
  if (node.kind === "lead") {
    const scheduled = agents.filter((a) => a.schedule_enabled && a.next_run_at).length;
    return [
      { id: "you", title: "You ask", note: "A message in Chat", role: "you", primary: true },
      {
        id: "schedule",
        title: "Your agents",
        note: scheduled ? `${scheduled} on a schedule` : "When you run one",
        role: "scheduler",
        primary: scheduled > 0,
      },
    ];
  }
  const agent = node.agent;
  const out: Trigger[] = [];
  if (agent?.schedule_text) {
    const on = agent.schedule_enabled && !!agent.next_run_at;
    out.push({
      id: "schedule",
      title: on ? "On schedule" : "Schedule paused",
      note: on ? `${agent.schedule_text} · next ${relativeTime(agent.next_run_at as string)}` : agent.schedule_text,
      role: "scheduler",
      primary: on,
    });
  }
  out.push({ id: "you", title: "You ask", note: "Run now, or @mention it in Chat", role: "you", primary: !agent?.schedule_text });
  return out;
}

function place(flow: Flow, triggers: Trigger[]): Placed {
  let top = 0;
  const stages = flow.steps.map((step) => {
    const tools = step.tools ?? [];
    const toolsH = tools.length ? tools.length * TOOL.step - (TOOL.step - TOOL.h) : 0;
    const block = Math.max(STAGE.h, toolsH);
    const placed = {
      title: step.title,
      detail: step.detail,
      icon: step.icon,
      asks: !!step.asks,
      helpers: step.helpers ?? [],
      y: top + (block - STAGE.h) / 2,
      tools: tools.map((name, j) => ({ name, y: top + (block - toolsH) / 2 + j * TOOL.step })),
    };
    top += block + GAP;
    return placed;
  });
  const trigBlock = triggers.length * TRIG.h + (triggers.length - 1) * 22;
  const height = Math.max(top - GAP, trigBlock, AGENT.h, OUT.h);
  const mid = height / 2;
  return {
    stages,
    triggers: triggers.map((t, k) => ({ ...t, y: mid - trigBlock / 2 + k * (TRIG.h + 22) })),
    agentY: mid - AGENT.h / 2,
    outY: mid - OUT.h / 2,
    height,
  };
}

const curve = (x1: number, y1: number, x2: number, y2: number) => {
  const m = (x1 + x2) / 2;
  return `M${x1} ${y1} C${m} ${y1}, ${m} ${y2}, ${x2} ${y2}`;
};

export default function AgentTreeGraph({
  node,
  live,
  agents,
}: {
  node: PanelNode;
  live: NodeLive | null;
  agents: Agent[];
}) {
  const box = useRef<HTMLElement>(null);
  const flow = flowFor(node.kind, node.role, node.agent);
  const triggers = useMemo(() => triggersFor(node, agents), [node, agents]);
  const layout = useMemo(() => (flow ? place(flow, triggers) : null), [flow, triggers]);

  // Bring the tree into view when an agent is picked, if it is off screen.
  useEffect(() => {
    box.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [node.id]);

  if (!flow || !layout) return null;

  const used = new Set((live?.story ?? []).filter((s) => s.kind === "tool" && s.tool).map((s) => s.tool as string));
  const working = live?.state === "working" || live?.state === "waiting";
  const H = layout.height;
  const agentMid = layout.agentY + AGENT.h / 2;
  const outMid = layout.outY + OUT.h / 2;

  // Every line, with when its dot should run in the cycle.
  const lines: { id: string; d: string; at: number; on: boolean }[] = [];
  for (const t of layout.triggers) {
    lines.push({ id: `t-${t.id}`, d: curve(TRIG.x + TRIG.w, t.y + TRIG.h / 2, AGENT.x, agentMid), at: 0, on: t.primary });
  }
  layout.stages.forEach((s, i) => {
    const sMid = s.y + STAGE.h / 2;
    lines.push({ id: `s-${i}`, d: curve(AGENT.x + AGENT.w, agentMid, STAGE.x, sMid), at: 0.9, on: true });
    s.tools.forEach((t, j) => {
      const tMid = t.y + TOOL.h / 2;
      lines.push({ id: `st-${i}-${j}`, d: curve(STAGE.x + STAGE.w, sMid, TOOL.x, tMid), at: 1.8, on: true });
      lines.push({ id: `to-${i}-${j}`, d: curve(TOOL.x + TOOL.w, tMid, OUT.x, outMid), at: 2.7, on: false });
    });
  });

  return (
    <section ref={box} className="flex flex-col gap-3 rounded-2xl border border-line bg-panel p-5" aria-label={`How ${node.name} works`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="font-display text-[18px] font-semibold tracking-[-0.01em]">How {node.name} works</h3>
        <span className="flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
          What starts it <Icon name="arrow" size={12} /> what it does <Icon name="arrow" size={12} /> what you get
          {used.size > 0 && <span className="text-ok-text">· ticked tools were used in its last run</span>}
        </span>
      </div>

      <div className="overflow-x-auto">
        <div className="agraph relative" style={{ width: WIDTH, height: H }} data-working={working || undefined}>
          <svg className="absolute inset-0 overflow-visible" width={WIDTH} height={H} aria-hidden="true">
            {lines.map((l) => (
              <path key={l.id} d={l.d} className={`agraph-line ${l.on ? "is-on" : ""}`} />
            ))}
            {lines.map((l) => (
              <circle key={`dot-${l.id}`} r="3.6" className="agraph-dot">
                <animateMotion dur={`${CYCLE}s`} begin={`${l.at}s`} repeatCount="indefinite" path={l.d} keyPoints="0;1;1" keyTimes="0;0.24;1" calcMode="linear" />
                <animate attributeName="opacity" dur={`${CYCLE}s`} begin={`${l.at}s`} repeatCount="indefinite" values="0;1;1;0;0" keyTimes="0;0.03;0.21;0.25;1" />
              </circle>
            ))}
          </svg>

          {layout.triggers.map((t) => (
            <div key={t.id} className={`agraph-node is-trigger ${t.primary ? "is-primary" : ""}`} style={{ left: TRIG.x, top: t.y, width: TRIG.w, height: TRIG.h }}>
              <span className="agraph-ic">
                <AgentAvatar role={t.role} size={20} />
              </span>
              <span className="min-w-0">
                <b>{t.title}</b>
                <small title={t.note}>{t.note}</small>
              </span>
            </div>
          ))}

          <div
            className="agraph-node is-agent"
            style={{ left: AGENT.x, top: layout.agentY, width: AGENT.w, height: AGENT.h, ["--tone" as string]: node.tone }}
          >
            <span className="agraph-ic is-big">
              {working && <span className="tn-ring" aria-hidden="true" />}
              <AgentAvatar role={node.role} size={30} />
            </span>
            <span className="min-w-0">
              <b>{node.name}</b>
              <small>{working ? "Working now" : node.kind === "helper" ? "Built-in helper" : node.kind === "lead" ? "Your assistant" : "Your agent"}</small>
            </span>
          </div>

          {layout.stages.map((s, i) => (
            <div
              key={s.title}
              className={`agraph-node is-stage ${s.asks ? "is-asks" : ""}`}
              style={{ left: STAGE.x, top: s.y, width: STAGE.w, height: STAGE.h }}
              title={s.detail}
            >
              <span className="agraph-ic">
                <Icon name={s.icon} size={16} strokeWidth={2} />
                <i>{i + 1}</i>
              </span>
              <span className="min-w-0">
                <b>{s.title}</b>
                {s.helpers.length > 0 ? (
                  <span className="agraph-helpers">
                    {s.helpers.map((h) => (
                      <AgentAvatar key={h} role={h} size={14} />
                    ))}
                  </span>
                ) : (
                  <small>{s.detail}</small>
                )}
              </span>
            </div>
          ))}

          {layout.stages.flatMap((s, i) =>
            s.tools.map((t) => {
              const service = serviceForTool(t.name);
              const wasUsed = used.has(t.name);
              return (
                <div
                  key={`${i}-${t.name}`}
                  className={`agraph-node is-tool ${wasUsed ? "is-used" : ""}`}
                  style={{ left: TOOL.x, top: t.y, width: TOOL.w, height: TOOL.h }}
                >
                  <span className="agraph-logo">
                    {service ? <ServiceMark service={service} size={18} /> : <Icon name={toolIcon(t.name)} size={15} />}
                  </span>
                  <span className="truncate" title={toolLabel(t.name)}>
                    {toolLabel(t.name)}
                  </span>
                  {wasUsed && (
                    <span className="agraph-tick" aria-label="used in the last run">
                      <Icon name="check" size={11} strokeWidth={3} />
                    </span>
                  )}
                </div>
              );
            }),
          )}

          <div className="agraph-node is-out" style={{ left: OUT.x, top: layout.outY, width: OUT.w, height: OUT.h }}>
            <span className="agraph-ic">
              <Icon name="check" size={16} strokeWidth={2.4} />
            </span>
            <span className="min-w-0">
              <small>You get</small>
              <b className="agraph-wrap">{flow.gives}</b>
            </span>
          </div>
        </div>
      </div>

      {flow.note && <p className="text-[13px] text-dim">{flow.note}</p>}
    </section>
  );
}

/** A plain icon for tools with no app of their own. */
function toolIcon(name: string) {
  if (/web|webpage/.test(name)) return "globe" as const;
  if (/recall|remember/.test(name)) return "memory" as const;
  if (name === "calculator") return "chart" as const;
  if (name === "current_time") return "clock" as const;
  if (name === "report_write") return "book" as const;
  if (name === "python_run") return "terminal" as const;
  if (/email|draft/.test(name)) return "mail" as const;
  return "zap" as const;
}
