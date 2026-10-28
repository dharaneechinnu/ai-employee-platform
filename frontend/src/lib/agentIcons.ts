import type { IconName } from "../components/icons";

/**
 * One icon and one colour per kind of agent, so the tree, the history
 * list and the cost table all draw the same agent the same way.
 *
 * Keys are the plain role names the team uses. A saved agent the person
 * made themselves has no role of its own and gets the generic mark.
 */
export type AgentRole =
  | "lead"
  | "researcher"
  | "analyst"
  | "writer"
  | "critic"
  | "developer"
  | "general"
  | "scheduled";

interface AgentLook {
  label: string;
  icon: IconName;
  /** A CSS variable from index.css, so it follows dark and light mode. */
  tone: string;
}

export const AGENT_LOOK: Record<AgentRole, AgentLook> = {
  lead: { label: "Lead assistant", icon: "tree", tone: "var(--accent)" },
  researcher: { label: "Researcher", icon: "search", tone: "var(--run)" },
  analyst: { label: "Analyst", icon: "chart", tone: "var(--ok)" },
  writer: { label: "Writer", icon: "pen", tone: "var(--ask)" },
  critic: { label: "Critic", icon: "scale", tone: "var(--bad)" },
  developer: { label: "Developer", icon: "code", tone: "var(--accent)" },
  general: { label: "General", icon: "sparkle", tone: "var(--dim)" },
  scheduled: { label: "Scheduled agent", icon: "clock", tone: "var(--run)" },
};

export function agentLook(role: string | null | undefined): AgentLook {
  // The team calls this helper "generalist"; it is drawn as General.
  const key = role === "generalist" ? "general" : role;
  return AGENT_LOOK[(key ?? "") as AgentRole] ?? AGENT_LOOK.scheduled;
}
