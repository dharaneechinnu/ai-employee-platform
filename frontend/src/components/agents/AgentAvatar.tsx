/**
 * A small picture for each kind of agent, so the Researcher looks like
 * a researcher and not like a search box. Drawn in two strokes of one
 * colour (`currentColor`), with a soft fill of the same colour, so each
 * badge follows the node's state colour and works in dark and light mode.
 */

import type { ReactElement } from "react";

type Role =
  | "lead"
  | "researcher"
  | "analyst"
  | "writer"
  | "critic"
  | "developer"
  | "general"
  | "agent"
  | "scheduler"
  | "you";

const ROLE_OF: Record<string, Role> = { generalist: "general", scheduled: "agent" };

function avatarRole(key: string | null | undefined): Role {
  const k = ROLE_OF[key ?? ""] ?? key ?? "agent";
  return (DRAWINGS as Record<string, unknown>)[k] ? (k as Role) : "agent";
}

const soft = { fill: "currentColor", fillOpacity: 0.16, stroke: "none" } as const;

const DRAWINGS: Record<Role, ReactElement> = {
  // A page of notes under a magnifying glass.
  researcher: (
    <>
      <rect x="3.5" y="2.5" width="12" height="15" rx="2" {...soft} />
      <rect x="3.5" y="2.5" width="12" height="15" rx="2" />
      <path d="M6.5 6.5h6M6.5 9.5h4" />
      <circle cx="15" cy="15" r="4" fill="var(--av-bg, var(--bg))" />
      <circle cx="15" cy="15" r="4" />
      <path d="M18 18l3 3" strokeWidth="2.2" />
    </>
  ),
  // Three bars and a rising trend line.
  analyst: (
    <>
      <rect x="3" y="12" width="4" height="8" rx="1" {...soft} />
      <rect x="10" y="8" width="4" height="12" rx="1" {...soft} />
      <rect x="17" y="4" width="4" height="16" rx="1" {...soft} />
      <path d="M3 20h18" />
      <path d="M4 10l6-4 4 3 7-6" />
      <path d="M17 3h4v4" />
    </>
  ),
  // A fountain pen nib drawing a line.
  writer: (
    <>
      <path d="M14 3l7 7-8.5 8.5L5 20l1.5-7.5z" {...soft} />
      <path d="M14 3l7 7-8.5 8.5L5 20l1.5-7.5z" />
      <path d="M5 20l5.5-5.5" />
      <circle cx="12" cy="12" r="1.6" />
      <path d="M3 22h8" />
    </>
  ),
  // A clipboard with a tick and a cross: checking a draft.
  critic: (
    <>
      <rect x="4" y="4" width="16" height="17" rx="2.5" {...soft} />
      <rect x="4" y="4" width="16" height="17" rx="2.5" />
      <path d="M9 2.5h6v3H9z" />
      <path d="M7.5 11l2 2 3.5-3.5" />
      <path d="M14.5 15.5l3 3M17.5 15.5l-3 3" />
    </>
  ),
  // A code window with angle brackets.
  developer: (
    <>
      <rect x="2.5" y="4" width="19" height="16" rx="2.5" {...soft} />
      <rect x="2.5" y="4" width="19" height="16" rx="2.5" />
      <path d="M2.5 8h19" />
      <path d="M9 12l-2.5 2.5L9 17M15 12l2.5 2.5L15 17M13 11.5l-2 6" />
    </>
  ),
  // Sparkles: good at a bit of everything.
  general: (
    <>
      <path d="M11 3l1.8 4.7L17.5 9.5l-4.7 1.8L11 16l-1.8-4.7L4.5 9.5l4.7-1.8z" {...soft} />
      <path d="M11 3l1.8 4.7L17.5 9.5l-4.7 1.8L11 16l-1.8-4.7L4.5 9.5l4.7-1.8z" />
      <path d="M18 15l.9 2.1 2.1.9-2.1.9L18 21l-.9-2.1L15 18l2.1-.9z" />
    </>
  ),
  // A hub handing work out to three helpers.
  lead: (
    <>
      <circle cx="12" cy="12" r="4" {...soft} />
      <circle cx="12" cy="12" r="4" />
      <circle cx="4.5" cy="5" r="2" />
      <circle cx="19.5" cy="5" r="2" />
      <circle cx="12" cy="21" r="1.8" />
      <path d="M6 6.5l3.2 3M18 6.5l-3.2 3M12 16v3.2" />
    </>
  ),
  // A friendly robot: an agent you made.
  agent: (
    <>
      <rect x="4" y="7" width="16" height="12" rx="3.5" {...soft} />
      <rect x="4" y="7" width="16" height="12" rx="3.5" />
      <path d="M12 3.5V7M2 12v3M22 12v3" />
      <circle cx="12" cy="3" r="1" />
      <circle cx="9" cy="12.5" r="1.3" fill="currentColor" />
      <circle cx="15" cy="12.5" r="1.3" fill="currentColor" />
      <path d="M9.5 16h5" />
    </>
  ),
  scheduler: (
    <>
      <circle cx="12" cy="13" r="8" {...soft} />
      <circle cx="12" cy="13" r="8" />
      <path d="M12 9v4l2.5 2.5M9 2.5h6" />
    </>
  ),
  you: (
    <>
      <circle cx="12" cy="8" r="4" {...soft} />
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c1-4.5 4.5-6.5 8-6.5s7 2 8 6.5" />
    </>
  ),
};

export default function AgentAvatar({ role, size = 22 }: { role: string | null | undefined; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {DRAWINGS[avatarRole(role)]}
    </svg>
  );
}
