import type { IconName } from "../icons";

/**
 * Every tip in the app. A step points at an element marked with
 * `data-coach="target"`; when that element is missing or hidden the step
 * is skipped, so admins and members, desktops and phones, all get a tour
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
    id: "tasks",
    route: "/tasks",
    steps: [
      {
        target: "setup",
        icon: "check",
        title: "Your setup checklist",
        body: "A few steps from nothing to your first finished task. It disappears once you're done.",
      },
      {
        target: "composer",
        icon: "chat",
        title: "Give work in plain words",
        body: "Describe the job the way you'd tell a colleague. No prompts, no code.",
      },
      {
        target: "employee-pick",
        icon: "employees",
        title: "Pick who does it",
        body: "Each AI Employee has its own job, its own tools and its own limits.",
      },
      {
        target: "voice",
        icon: "mic",
        title: "Or just say it",
        body: "Press the mic and talk. Your words land in the box so you can check them before sending.",
      },
      {
        target: "dry-run",
        icon: "shield",
        title: "Try it safely first",
        body: "Dry run plans the whole job but sends and changes nothing. Perfect for a first go.",
      },
      {
        target: "task-list",
        icon: "tasks",
        title: "Everything, on record",
        body: "Every task and every step is kept. Filter by what's running, what needs you, and what's done.",
      },
      {
        target: "nav-approvals",
        icon: "approvals",
        adminOnly: true,
        title: "Risky actions wait for you",
        body: "Before an AI Employee sends or changes anything important, it pauses here until a person decides.",
      },
    ],
  },
  {
    id: "run",
    appears: "run-panel",
    steps: [
      {
        target: "run-stats",
        icon: "info",
        title: "What it took",
        body: "Steps taken, how much AI it used and an estimated cost, for this one task.",
      },
      {
        target: "run-tabs",
        icon: "tree",
        title: "Three ways to watch",
        body: "Timeline shows each step live. Agent tree shows who helped. Result is the finished answer.",
      },
      {
        target: "run-cancel",
        icon: "x",
        title: "Stop it any time",
        body: "Changed your mind? Cancel stops the run within one step.",
      },
    ],
  },
  {
    id: "employees",
    route: "/employees",
    steps: [
      {
        target: "employee-card",
        icon: "employees",
        title: "Meet your AI Employee",
        body: "Its job in one line, whether it's working, which AI does its thinking and how many tools it has.",
      },
      {
        target: "employee-switch",
        icon: "check",
        adminOnly: true,
        title: "On or off",
        body: "A paused AI Employee takes no new work. Nothing is deleted, and you can switch it back on any time.",
      },
      {
        target: "employee-tools",
        icon: "sparkle",
        adminOnly: true,
        title: "Tools & AI",
        body: "Choose exactly what it can use. A tool you don't tick doesn't exist for it.",
      },
      {
        target: "templates",
        icon: "copy",
        adminOnly: true,
        title: "Start from a template",
        body: "Ready-made jobs for support, sales, HR and ops, with the right tools already ticked.",
      },
      {
        target: "new-employee",
        icon: "plus",
        adminOnly: true,
        title: "Or build your own",
        body: "Three plain questions: what it does, what it must never do, and when to ask you first.",
      },
    ],
  },
  {
    id: "tools-panel",
    appears: "tools-panel",
    steps: [
      {
        target: "model-select",
        icon: "providers",
        title: "Which AI does the thinking",
        body: "Automatic uses whichever AI key your company connected. Pin a specific one if you prefer.",
      },
      {
        target: "tool-picker",
        icon: "lock",
        title: "Tick only what it needs",
        body: "The tags say what each tool can do. Anything that can't be undone still waits for your approval.",
      },
    ],
  },
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
        body: "The AI Employee stops cleanly and nothing is done.",
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
        body: "Facts saved here are remembered by every AI Employee in every later task.",
      },
      {
        target: "memory-list",
        icon: "database",
        title: "What it knows",
        body: "Everything your AI team remembers, shared company-wide or kept to one employee.",
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
        title: "When may it act?",
        body: "On its own, ask a person first, or blocked. Your choice saves the moment you click.",
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
        body: "Sign in once. Your AI Employees can then work in email, calendars and files, and never see your password.",
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
        title: "Choose what you hear about",
        body: "Approvals, failures, finished work: switch each one on or off.",
      },
    ],
  },
  {
    id: "members",
    route: "/members",
    steps: [
      {
        target: "members-invite",
        icon: "plus",
        adminOnly: true,
        title: "Bring in your team",
        body: "Members give out tasks. Admins also set up AI Employees and decide approvals.",
      },
      {
        target: "member-actions",
        icon: "members",
        adminOnly: true,
        title: "Change roles any time",
        body: "Make someone an admin, or remove access straight away.",
      },
    ],
  },
];
