import type { IconName } from "../components/icons";

/**
 * Everything the command palette and the shortcut sheet know about.
 *
 * One list feeds both, so a shortcut can never be on the sheet and
 * missing from the palette (or the other way round). A screen that
 * arrives later, such as History, adds a line here.
 *
 * `keys` is what is shown: ["G", "K"] means press G, then K. `go` is the
 * second key of a "G then ..." jump; `key` is a single key.
 */
export interface Command {
  id: string;
  label: string;
  group: "Go to" | "Actions";
  icon: IconName;
  to: string;
  go?: string;
  key?: string;
}

export const COMMANDS: Command[] = [
  { id: "new-chat", label: "New chat", group: "Actions", icon: "plus", to: "/chat", key: "n" },
  { id: "connect-ai", label: "Connect an AI", group: "Actions", icon: "key", to: "/providers" },

  { id: "go-chat", label: "Chat", group: "Go to", icon: "chat", to: "/chat", go: "c" },
  { id: "go-agents", label: "AI Agents", group: "Go to", icon: "employees", to: "/agents", go: "a" },
  { id: "go-tree", label: "Agent tree", group: "Go to", icon: "tree", to: "/agents?tab=tree", go: "t" },
  { id: "go-history", label: "History", group: "Go to", icon: "history", to: "/agents?tab=history", go: "h" },
  { id: "go-approvals", label: "Approvals", group: "Go to", icon: "approvals", to: "/approvals", go: "p" },
  { id: "go-memory", label: "Memory", group: "Go to", icon: "memory", to: "/memory", go: "m" },
  { id: "go-usage", label: "Models and cost", group: "Go to", icon: "wallet", to: "/agents?tab=cost", go: "u" },
  { id: "go-connections", label: "Connections", group: "Go to", icon: "link", to: "/connections", go: "o" },
  { id: "go-keys", label: "AI keys", group: "Go to", icon: "providers", to: "/providers", go: "k" },
  { id: "go-permissions", label: "Permissions", group: "Go to", icon: "lock", to: "/policies", go: "r" },
  { id: "go-notifications", label: "Notifications", group: "Go to", icon: "bell", to: "/notifications", go: "n" },
];

/** The keys to show for a command, as separate caps. */
export function keysFor(c: Command): string[] {
  if (c.go) return ["G", c.go.toUpperCase()];
  if (c.key) return [c.key.toUpperCase()];
  return [];
}

/** Shortcuts that do something on the page itself rather than go somewhere. */
export const PAGE_SHORTCUTS: { label: string; keys: string[] }[] = [
  { label: "Command palette", keys: ["Ctrl", "K"] },
  { label: "Search this page", keys: ["/"] },
  { label: "All shortcuts", keys: ["?"] },
  { label: "Close", keys: ["Esc"] },
];

/** True when the keyboard is busy typing, so single keys must stay quiet. */
export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}
