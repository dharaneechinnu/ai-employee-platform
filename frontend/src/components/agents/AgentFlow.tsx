import type { Agent } from "../../lib/api";
import { toolLabel } from "../../lib/labels";
import { Icon, type IconName } from "../icons";
import AgentAvatar from "./AgentAvatar";

/**
 * How an agent works, drawn as a small graph: what comes in, each step
 * in order with the tools it uses, and what it hands back. The built-in
 * helpers have a fixed way of working (their tools are set in the
 * backend's `team.py`); an agent you made is drawn from its own tools.
 */

interface FlowStep {
  title: string;
  detail: string;
  icon: IconName;
  tools?: string[];
  /** A step that changes or sends something, so it may ask you first. */
  asks?: boolean;
  /** Helpers this step can bring in (the lead only). */
  helpers?: string[];
}

interface Flow {
  gets: string;
  steps: FlowStep[];
  gives: string;
  note?: string;
}

const HELPER_NOTE = "Helpers can only read. They never change, send or delete anything.";

const FLOWS: Record<string, Flow> = {
  lead: {
    gets: "Your message in Chat, or an agent's job",
    steps: [
      {
        title: "Picks the right AI",
        detail: "Reads the task (coding, writing, analysis…) and sends it to the connected model best at it. If that one is busy, the next takes over.",
        icon: "cpu",
      },
      {
        title: "Checks what it knows",
        detail: "Looks in your memory before asking you something you already said.",
        icon: "memory",
        tools: ["recall"],
      },
      {
        title: "Does the work",
        detail: "Uses the tools your Permissions allow, in your connected apps and on the web.",
        icon: "zap",
        tools: ["web_search", "gmail_search", "sheets_read", "calculator"],
      },
      {
        title: "Brings in helpers",
        detail: "For bigger jobs, hands parts to specialists and works on several at once.",
        icon: "tree",
        helpers: ["researcher", "analyst", "writer", "critic", "developer", "generalist"],
      },
      {
        title: "Never acts without your say",
        detail: "Sending, posting or cancelling stays blocked until you allow it, or waits for your yes in the app, by email or in Slack.",
        icon: "approvals",
        asks: true,
      },
    ],
    gives: "The answer, with every step and its cost on record",
  },
  researcher: {
    gets: "A question from your assistant",
    steps: [
      { title: "Plans what to look up", detail: "Splits the question into a few short searches.", icon: "tree" },
      {
        title: "Searches",
        detail: "The web, and your connected apps when the answer is yours.",
        icon: "search",
        tools: ["web_search", "gmail_search", "google_drive_search", "onedrive_search"],
      },
      {
        title: "Reads the best sources",
        detail: "Opens pages, files and PDFs and keeps what matters.",
        icon: "book",
        tools: ["get_webpage", "google_drive_read", "onedrive_read", "gmail_read"],
      },
      {
        title: "Checks the facts",
        detail: "Cross-checks numbers and dates, and marks anything uncertain.",
        icon: "check",
        tools: ["calculator", "current_time", "text_tools"],
      },
    ],
    gives: "A short report, with where each fact came from",
    note: HELPER_NOTE,
  },
  analyst: {
    gets: "Numbers, data or options to weigh",
    steps: [
      {
        title: "Gathers the data",
        detail: "From your sheets, Excel workbooks, files and database.",
        icon: "database",
        tools: ["sheets_read", "excel_read", "run_query", "google_drive_read", "onedrive_read"],
      },
      {
        title: "Works it out exactly",
        detail: "Every sum, percentage and average goes through the calculator.",
        icon: "chart",
        tools: ["calculator", "text_tools"],
      },
      { title: "Compares the options", detail: "States its assumptions and weighs each choice step by step.", icon: "scale" },
    ],
    gives: "A clear recommendation, with the working shown",
    note: HELPER_NOTE,
  },
  writer: {
    gets: "The facts, and who the text is for",
    steps: [
      { title: "Outlines", detail: "Orders the material for the reader.", icon: "menu" },
      { title: "Drafts", detail: "Writes it plainly, keeping every fact and adding none.", icon: "pen", tools: ["text_tools"] },
      {
        title: "Builds the report",
        detail: "Assembles a finished document with its sources when one is asked for.",
        icon: "book",
        tools: ["report_write", "current_time"],
      },
    ],
    gives: "Finished text, ready to send or share",
    note: HELPER_NOTE,
  },
  critic: {
    gets: "A draft or a claim to check",
    steps: [
      { title: "Reads it closely", detail: "Looks for errors, gaps, weak reasoning and unclear wording.", icon: "eye" },
      { title: "Checks the figures", detail: "Redoes the sums.", icon: "chart", tools: ["calculator"] },
      {
        title: "Checks the sources",
        detail: "Looks up quoted facts where it can.",
        icon: "search",
        tools: ["web_search", "get_webpage"],
      },
      { title: "Ranks the problems", detail: "Most important first, each with a fix.", icon: "filter", tools: ["text_tools"] },
    ],
    gives: "A list of problems in order, with a fix for each",
    note: HELPER_NOTE,
  },
  developer: {
    gets: "A code question, a bug or a pull request",
    steps: [
      {
        title: "Finds the code",
        detail: "Searches your repositories for the files that matter.",
        icon: "search",
        tools: ["github_list_repos", "github_search_code"],
      },
      {
        title: "Reads it",
        detail: "Opens the files, the pull request's changes and the issue.",
        icon: "code",
        tools: ["github_read_file", "github_pr_diff", "github_read_issue"],
      },
      {
        title: "Checks CI and history",
        detail: "Why the build is red, and what changed recently.",
        icon: "history",
        tools: ["github_ci_status", "github_list_commits"],
      },
      {
        title: "Looks up the error",
        detail: "Searches the docs and the web for the message.",
        icon: "globe",
        tools: ["web_search", "get_webpage"],
      },
    ],
    gives: "The fix or the review, naming the files it read",
    note: HELPER_NOTE,
  },
  generalist: {
    gets: "Any task that needs no specialist",
    steps: [
      { title: "Understands the task", detail: "Works out what is really being asked.", icon: "info" },
      {
        title: "Uses what fits",
        detail: "Any read-only tool you have, from the web to your files.",
        icon: "zap",
        tools: ["web_search", "get_webpage", "google_drive_read", "calculator"],
      },
      { title: "Answers plainly", detail: "Or says what is missing instead of guessing.", icon: "chat" },
    ],
    gives: "A plain answer",
    note: HELPER_NOTE,
  },
};

const ACTS = /send|_post$|_cancel$/;
const CHANGES = /create|append|update|draft|organize|comment|propose|remember|save|python_run/;
const WORKS = /^(calculator|current_time|text_tools|report_write)$/;

/** An agent you made: its own tools, put in the order a run uses them. */
function agentFlow(agent: Agent): Flow {
  const tools = agent.tools ?? [];
  const recall: string[] = tools.filter((t) => t === "recall");
  const acts = tools.filter((t) => ACTS.test(t));
  const changes = tools.filter((t) => !ACTS.test(t) && CHANGES.test(t));
  const works = tools.filter((t) => WORKS.test(t));
  const reads = tools.filter((t) => !recall.includes(t) && !acts.includes(t) && !changes.includes(t) && !works.includes(t));
  const steps: FlowStep[] = [];
  if (recall.length) steps.push({ title: "Remembers your preferences", detail: "Checks what you told it before.", icon: "memory", tools: recall });
  if (reads.length) steps.push({ title: "Looks things up", detail: "Reads what the job needs, in your apps and on the web.", icon: "search", tools: reads });
  if (works.length) steps.push({ title: "Works it out", detail: "Exact sums, dates and text checks.", icon: "chart", tools: works });
  if (changes.length) steps.push({ title: "Makes the changes", detail: "Drafts, rows, events and labels: things you can undo.", icon: "pen", tools: changes });
  if (acts.length)
    steps.push({ title: "Sends or posts", detail: "Can't be undone, so it follows your Permissions: blocked, ask first, or allowed.", icon: "approvals", tools: acts, asks: true });
  if (!steps.length) steps.push({ title: "Works with every tool you allow", detail: "No list was set, so your Permissions decide.", icon: "zap" });
  return {
    gets: agent.schedule_enabled && agent.schedule_text ? `On schedule: ${agent.schedule_text}` : "When you ask, or @mention it in Chat",
    steps,
    gives: "The result, saved in its own chat",
  };
}

export function hasFlow(kind: string, key: string): boolean {
  return kind === "agent" || kind === "lead" || key in FLOWS;
}

export default function AgentFlow({
  kind,
  flowKey,
  agent,
  name,
}: {
  kind: string;
  flowKey: string;
  agent: Agent | null;
  name: string;
}) {
  const flow = kind === "agent" && agent ? agentFlow(agent) : FLOWS[kind === "lead" ? "lead" : flowKey];
  if (!flow) return null;
  return (
    <section className="flex flex-col gap-2" aria-label={`How ${name} works`}>
      <div className="text-[12.5px] font-semibold text-muted">How {name} works</div>
      <ol className="aflow stagger">
        <li className="aflow-end is-in">
          <span className="aflow-dot" aria-hidden="true">
            <Icon name="arrow" size={13} strokeWidth={2.2} />
          </span>
          <span className="min-w-0">
            <small>Gets</small>
            <b>{flow.gets}</b>
          </span>
        </li>
        {flow.steps.map((step, i) => (
          <li key={step.title} className={`aflow-step ${step.asks ? "is-asks" : ""}`}>
            <span className="aflow-dot" aria-hidden="true">
              <Icon name={step.icon} size={14} strokeWidth={2} />
              <i>{i + 1}</i>
            </span>
            <span className="min-w-0">
              <b>{step.title}</b>
              <span className="aflow-detail">{step.detail}</span>
              {step.tools && step.tools.length > 0 && (
                <span className="aflow-tools">
                  {step.tools.map((t) => (
                    <span key={t}>{toolLabel(t)}</span>
                  ))}
                </span>
              )}
              {step.helpers && (
                <span className="aflow-helpers">
                  {step.helpers.map((h) => (
                    <span key={h} title={h}>
                      <AgentAvatar role={h} size={16} />
                    </span>
                  ))}
                </span>
              )}
            </span>
          </li>
        ))}
        <li className="aflow-end is-out">
          <span className="aflow-dot" aria-hidden="true">
            <Icon name="check" size={13} strokeWidth={2.4} />
          </span>
          <span className="min-w-0">
            <small>Gives back</small>
            <b>{flow.gives}</b>
          </span>
        </li>
      </ol>
      {flow.note && <p className="text-[12.5px] text-dim">{flow.note}</p>}
    </section>
  );
}
