import { useState } from "react";
import { Button, Card, ErrorNote, Input, TextArea, useToast } from "../ui";
import {
  ApiError,
  api,
  type Agent,
  type AgentSchedule,
  type AgentStarter,
  type RunNowResult,
} from "../../lib/api";
import ScheduleEditor from "./ScheduleEditor";

/**
 * One short form for a built-in starter: say what it should do, pick
 * when it runs, and press Create or Create and run now. The starter's
 * own role text is kept and your instructions are added after it, so
 * there is nothing to find and open afterwards.
 */
export default function StarterSetup({
  starter,
  onCancel,
  onCreated,
  onStarted,
}: {
  starter: AgentStarter;
  onCancel: () => void;
  /** The agent was saved (and not run). */
  onCreated: (agent: Agent) => void | Promise<void>;
  /** The agent was saved and started: open its chat. */
  onStarted: (conversationId: string) => void;
}) {
  const toast = useToast();
  const [name, setName] = useState(`My ${starter.name}`);
  const [job, setJob] = useState("");
  const [schedule, setSchedule] = useState<AgentSchedule | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = name.trim().length > 0 && job.trim().length >= 10;

  async function save(thenRun: boolean) {
    setBusy(true);
    setError(null);
    let agent: Agent;
    try {
      agent = await api.post<Agent>("/me/agents", {
        name: name.trim(),
        description: starter.description,
        instructions: `${starter.instructions}\n\n${job.trim()}`,
        // No list: the platform works out the tools from the instructions.
        tools: null,
        schedule,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create it.");
      setBusy(false);
      return;
    }

    if (!thenRun) {
      toast(
        schedule
          ? `${agent.name} is created and scheduled.`
          : `${agent.name} is created. Press Run now on its card when you want it.`,
      );
      setBusy(false);
      await onCreated(agent);
      return;
    }

    try {
      const result = await api.post<RunNowResult>(`/me/agents/${agent.id}/run`, {});
      if (result.status === "started" && result.conversation_id) {
        onStarted(result.conversation_id);
        return;
      }
      toast(
        result.status === "busy"
          ? "It is still running its last job."
          : "Saved, but it could not start. See what needs fixing on its card.",
      );
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Saved, but it could not start.");
    }
    setBusy(false);
    await onCreated(agent);
  }

  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-baseline gap-2">
        <h3 className="font-display text-[16px] font-semibold">Set up a {starter.name}</h3>
        <span className="text-[12px] uppercase tracking-wider text-dim">
          {starter.kind === "mode" ? "style" : "teammate"}
        </span>
      </div>
      <p className="text-[13px] text-muted">
        Starts as: “{starter.instructions.length > 140 ? `${starter.instructions.slice(0, 140)}…` : starter.instructions}”
        Your instructions below are added to it.
      </p>

      <Input label="Name" value={name} onChange={setName} />
      <TextArea
        label="What should it do?"
        value={job}
        onChange={setJob}
        rows={5}
        placeholder="For example: Every morning, find free developer meetups in Chennai and add them to my sheet."
      />

      <div className="rounded-xl border border-line bg-panel p-3">
        <ScheduleEditor value={schedule} onChange={setSchedule} />
      </div>

      <p className="text-[13px] text-dim">
        You don’t need to pick tools. It gets what your instructions call for, such as searching the web or updating a sheet.
      </p>

      <ErrorNote message={error} />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" icon="check" disabled={busy || !ready} onClick={() => void save(false)}>
          {schedule ? "Create and schedule" : "Create"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          icon="arrow"
          disabled={busy || !ready}
          title="Create it and start it now"
          onClick={() => void save(true)}
        >
          Create and run now
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </Card>
  );
}
