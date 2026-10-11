import { useEffect, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  Input,
  Spinner,
  TextArea,
  statusTone,
} from "../components/ui";
import { ApiError, api, type EmployeeList, type Template } from "../lib/api";
import { useAuth, useIsAdmin } from "../lib/auth";

/**
 * Phase 2. The creation form asks guided questions rather than offering
 * one empty instructions box: the people using this are sales and HR,
 * and "be helpful" produces a bad worker they then blame the product
 * for.
 */
export default function Employees() {
  const { org } = useAuth();
  const isAdmin = useIsAdmin();

  const [list, setList] = useState<EmployeeList | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [does, setDoes] = useState("");
  const [never, setNever] = useState("");
  const [askHuman, setAskHuman] = useState("");

  async function load() {
    if (!org) return;
    setList(await api.get<EmployeeList>(`/orgs/${org.id}/ai-employees`));
    setTemplates(await api.get<Template[]>(`/orgs/${org.id}/templates`));
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org?.id]);

  function applyTemplate(template: Template) {
    const guided = template.config.guided;
    setName(template.name);
    setDoes(guided?.what_it_does ?? "");
    setNever(guided?.what_it_must_never_do ?? "");
    setAskHuman(guided?.when_to_ask_a_human ?? "");
    setCreating(true);
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!org) return;
    setError(null);
    try {
      await api.post(`/orgs/${org.id}/ai-employees`, {
        name,
        job_title: jobTitle || null,
        config: {
          guided: {
            what_it_does: does,
            what_it_must_never_do: never || null,
            when_to_ask_a_human: askHuman || null,
          },
        },
      });
      setCreating(false);
      setName("");
      setDoes("");
      setNever("");
      setAskHuman("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create it.");
    }
  }

  async function setStatus(id: string, action: "activate" | "pause") {
    if (!org) return;
    await api.post(`/orgs/${org.id}/ai-employees/${id}/${action}`);
    await load();
  }

  if (!list) return <Spinner />;

  const atLimit = list.used >= list.limit;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg">AI Employees</h1>
        <Badge tone={atLimit ? "amber" : "gray"}>
          {list.used} of {list.limit} used
        </Badge>
        {isAdmin && !creating && (
          <div className="ml-auto">
            <Button onClick={() => setCreating(true)} disabled={atLimit}>
              New AI Employee
            </Button>
          </div>
        )}
      </div>

      {atLimit && isAdmin && (
        <p className="text-xs text-amber-400">
          You have reached your limit. Archive one, or ask support to raise it.
        </p>
      )}

      {creating && (
        <Card>
          <form onSubmit={create} className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Input label="Name" value={name} onChange={setName} required />
              <Input label="Job title" value={jobTitle} onChange={setJobTitle} />
            </div>
            <TextArea
              label="What should it do?"
              value={does}
              onChange={setDoes}
              placeholder="Read bug reports, find the code, and open a fix."
            />
            <TextArea
              label="What must it never do?"
              value={never}
              onChange={setNever}
              placeholder="Never delete code. Never push to main."
            />
            <TextArea
              label="When should it ask a human first?"
              value={askHuman}
              onChange={setAskHuman}
              placeholder="Before opening a pull request."
            />
            <ErrorNote message={error} />
            <div className="flex gap-2">
              <Button type="submit">Create</Button>
              <Button variant="ghost" onClick={() => setCreating(false)}>
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}

      {list.items.length === 0 && !creating ? (
        <Empty
          message="No AI Employees yet."
          hint={isAdmin ? "Start from a template below." : "An admin needs to create one."}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {list.items.map((employee) => (
            <Card key={employee.id}>
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm">{employee.name}</p>
                  <p className="text-xs text-neutral-500">{employee.job_title ?? "—"}</p>
                </div>
                <Badge tone={statusTone(employee.status)}>{employee.status}</Badge>
              </div>
              {isAdmin && (
                <div className="mt-3 flex gap-2">
                  {employee.status !== "active" ? (
                    <Button variant="ghost" onClick={() => void setStatus(employee.id, "activate")}>
                      Activate
                    </Button>
                  ) : (
                    <Button variant="ghost" onClick={() => void setStatus(employee.id, "pause")}>
                      Pause
                    </Button>
                  )}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {isAdmin && templates.length > 0 && (
        <section>
          <h2 className="mb-2 mt-6 text-sm text-neutral-400">Start from a template</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {templates.map((template) => (
              <Card key={template.id}>
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm">{template.name}</p>
                  {!template.is_platform_template && <Badge tone="blue">yours</Badge>}
                </div>
                <p className="mt-1 text-xs text-neutral-500">{template.description}</p>
                <div className="mt-3">
                  <Button variant="ghost" onClick={() => applyTemplate(template)}>
                    Use
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
