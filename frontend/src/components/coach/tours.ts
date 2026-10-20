import type { IconName } from "../icons";

/**
 * Every tip in the app. A step points at an element marked with
 * `data-coach="target"`; when that element is missing or hidden the step
 * is skipped, so desktops and phones both get a tour
 * that fits what they can see.
 *
 * `route` tours run on the first visit to a screen. `appears` tours run
 * the first time their element shows up: a panel opening, a first run,
 * a first approval. That is "teach it when they reach for it".
 */

export type CoachStep = {
  target?: string;
  title: string;
  body: string;
  icon?: IconName;
  adminOnly?: boolean;
};

export type Tour = {
  id: string;
  route?: string;
  appears?: string;
  steps: CoachStep[];
};

export const TOURS: Tour[] = [
  {
    id: "approval",
    appears: "approval-action",
    steps: [
      {
        target: "approval-action",
        icon: "eye",
        title: "Read exactly what will happen",
        body: "The whole email or action, word for word. Nothing is summarised away.",
      },
      {
        target: "approval-approve",
        icon: "check",
        title: "Hold to approve",
        body: "Things that can't be undone need a one-second hold, so a slip of the finger can't send anything.",
      },
      {
        target: "approval-reject",
        icon: "x",
        title: "Or say no",
        body: "Your assistant stops cleanly and nothing is done.",
      },
    ],
  },
  {
    id: "memory",
    route: "/memory",
    steps: [
      {
        target: "memory-search",
        icon: "search",
        title: "Search the way you think",
        body: "Find things by meaning, like \"refund rules\", or by exact words, like an error code.",
      },
      {
        target: "memory-teach",
        icon: "memory",
        title: "Teach it once",
        body: "Facts saved here are remembered by your assistant in every later chat.",
      },
      {
        target: "memory-list",
        icon: "database",
        title: "What it knows",
        body: "Everything your assistant remembers about you and your work. Forget anything, any time.",
      },
    ],
  },
  {
    id: "policies",
    route: "/policies",
    steps: [
      {
        target: "policy-choice",
        icon: "lock",
        title: "Always allow, ask me first, or blocked",
        body: "Always allow runs with no approval. Ask me first waits for a person. Blocked never runs. It saves the moment you click.",
      },
      {
        target: "policy-advanced",
        icon: "chevrons",
        title: "One switch for a whole app",
        body: "Set a rule for every action of a kind in an app, like everything Gmail can't undo.",
      },
    ],
  },
  {
    id: "connections",
    route: "/connections",
    steps: [
      {
        target: "connection-card",
        icon: "link",
        title: "Connect your apps in one click",
        body: "Sign in once. Your assistant can then work in email, calendars and files, and never sees your password.",
      },
      {
        target: "connection-permissions",
        icon: "lock",
        adminOnly: true,
        title: "Decide what each tool may do",
        body: "Always allow runs it with no approval, Ask me first waits for you, Blocked never runs. Set it per tool, right here.",
      },
    ],
  },
  {
    id: "providers",
    route: "/providers",
    steps: [
      {
        target: "provider-form",
        icon: "providers",
        title: "Bring your own AI key",
        body: "Your key, your bill. It's encrypted the moment you save it and can never be read back, even by us.",
      },
    ],
  },
  {
    id: "notifications",
    route: "/notifications",
    steps: [
      {
        target: "notify-channels",
        icon: "bell",
        title: "Hear about it where you work",
        body: "Email or a Slack channel, with Approve and Reject buttons right in the message.",
      },
      {
        target: "notify-when",
        icon: "check",
        title: "Choose when to hear from it",
        body: "Switch approval requests on or off.",
      },
    ],
  },
];
