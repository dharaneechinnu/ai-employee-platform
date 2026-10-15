import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Icon } from "../components/icons";
import {
  Button,
  Chip,
  Empty,
  ErrorNote,
  PageBody,
  PageHeader,
  Select,
  Spinner,
  Tabs,
  TextArea,
  relativeTime,
  useToast,
  type Tone,
} from "../components/ui";
import { ApiError, api, type EmbeddingConfig, type MemoryItem } from "../lib/api";
import { formatDateTime } from "../lib/labels";
import { useAuth, useIsAdmin } from "../lib/auth";

interface SearchHit {
  id: string;
  content: string;
  kind: string;
  score: number;
  matched_by: string;
}

/**
 * Phase 6. Search is hybrid: meaning plus keyword. Each hit reports
 * which half found it, which matters because a vector model is weak on
 * exact strings like error codes and file names.
 */

type Scope = "all" | "org" | "employee";

const KIND_TONE: Record<string, Tone> = { fact: "run", correction: "ask", summary: "ok", document: "brand" };

export default function Memory() {
  const { org } = useAuth();
  const isAdmin = useIsAdmin();
  const toast = useToast();

  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [config, setConfig] = useState<EmbeddingConfig | null>(null);
  const [scope, setScope] = useState<Scope>("all");
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [draft, setDraft] = useState("");
  const [kind, setKind] = useState("fact");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    if (!org) return;
    setItems(await api.get<MemoryItem[]>(`/orgs/${org.id}/memory`));
    setConfig(await api.get<EmbeddingConfig>(`/orgs/${org.id}/embedding-config`));
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org?.id]);

  async function search(e: React.FormEvent) {
    e.preventDefault();
    if (!org) return;
    if (!query.trim()) {
      setHits(null);
      setSearched("");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      setHits(await api.post<SearchHit[]>(`/orgs/${org.id}/memory/search`, { query, limit: 10 }));
      setSearched(query.trim());
    } catch (err) {
      // A mismatch between embedding models is surfaced, never papered
      // over: searching across two models returns confident nonsense.
      setError(err instanceof ApiError ? err.message : "Search failed.");
      setHits(null);
    } finally {
      setBusy(false);
    }
  }

  async function add() {
    if (!org || !draft.trim()) return;
    try {
      await api.post(`/orgs/${org.id}/memory`, { content: draft, kind });
      setDraft("");
      toast("Remembered. Every AI Employee can recall it now.");
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not save that.", "bad");
    }
  }

  async function forget(item: MemoryItem) {
    if (!org) return;
    try {
      await api.del(`/orgs/${org.id}/memory/${item.id}`);
      setItems((current) => current?.filter((m) => m.id !== item.id) ?? null);
      setHits((current) => current?.filter((h) => h.id !== item.id) ?? null);
      toast("Forgotten.", "info");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not forget that.", "bad");
    }
  }

  async function reembed() {
    if (!org) return;
    await api.post(`/orgs/${org.id}/embedding-config/reembed`);
    setError(null);
    toast("Refreshing search. It finishes in the background.", "info");
    await load();
  }

  const visible = useMemo(
    () => (items ?? []).filter((item) => scope === "all" || item.scope === scope),
    [items, scope],
  );

  if (!items || !config) {
    return (
      <>
        <PageHeader crumb="Team" title="Memory" />
        <Spinner />
      </>
    );
  }

  const byId = new Map(items.map((m) => [m.id, m]));

  return (
    <>
      <PageHeader crumb="Team" title="Memory" />
      <PageBody>
        <div className="flex flex-wrap items-start gap-5">
          <section className="flex min-w-0 flex-[999_1_480px] flex-col gap-3.5">
            <form
              data-coach="memory-search"
              onSubmit={search}
              className="rise flex h-14 items-center gap-3 rounded-2xl border border-accent bg-sunken px-4"
              style={{ boxShadow: "0 0 0 4px var(--accent-soft), 0 20px 50px -30px var(--glow)" }}
            >
              <Icon name="search" size={20} strokeWidth={2} className="text-accent-text" />
              <label className="flex min-w-0 flex-1">
                <span className="sr-only">Search memory</span>
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search by meaning or exact words, like refund policy"
                  className="min-w-0 flex-1 border-0 bg-transparent font-mono text-base text-ink outline-none placeholder:font-sans placeholder:text-dim"
                />
              </label>
              <Button type="submit" size="sm" variant="ghost" disabled={busy}>
                {busy ? "Searching…" : "Search"}
              </Button>
            </form>

            <ErrorNote message={error} />

            {hits ? (
              <>
                <div className="flex items-center gap-3 text-[13px] text-muted">
                  <span>
                    {hits.length} result{hits.length === 1 ? "" : "s"} for <b className="font-mono text-ink">{searched}</b>
                  </span>
                  <button type="button" className="ml-auto text-accent-text hover:underline" onClick={() => { setHits(null); setQuery(""); }}>
                    Clear search
                  </button>
                </div>
                {hits.length === 0 ? (
                  <Empty message="Nothing found" hint="Try different words. Search matches meaning, not only exact text." />
                ) : (
                  hits.map((hit, i) => (
                    <MemoryCard
                      key={hit.id}
                      index={i}
                      content={<Highlight text={hit.content} term={searched} />}
                      kind={hit.kind}
                      meta={
                        <Chip tone={hit.matched_by === "both" ? "ok" : "mute"} dot={false}>
                          matched by {hit.matched_by}
                        </Chip>
                      }
                      onForget={isAdmin && byId.get(hit.id) ? () => void forget(byId.get(hit.id)!) : undefined}
                    />
                  ))
                )}
              </>
            ) : (
              <>
                <Tabs
                  label="Who knows it"
                  value={scope}
                  onChange={setScope}
                  items={[
                    { key: "all", label: "All", count: items.length },
                    { key: "org", label: "Whole company", count: items.filter((m) => m.scope === "org").length },
                    { key: "employee", label: "One employee", count: items.filter((m) => m.scope === "employee").length },
                  ]}
                />
                {visible.length === 0 ? (
                  <Empty
                    message="Nothing remembered yet"
                    hint="Teach it facts about your company. AI Employees also save lessons from finished runs."
                  />
                ) : (
                  visible.map((item, i) => (
                    <MemoryCard
                      key={item.id}
                      index={i}
                      content={item.content}
                      kind={item.kind}
                      meta={
                        <>
                          <Chip tone="mute" dot={false}>
                            {item.scope === "org" ? "company" : "one employee"}
                          </Chip>
                          <span className="text-dim" title={formatDateTime(item.created_at)}>
                            {relativeTime(item.created_at)}
                          </span>
                        </>
                      }
                      onForget={isAdmin ? () => void forget(item) : undefined}
                    />
                  ))
                )}
              </>
            )}
          </section>

          <div className="flex min-w-0 flex-[1_1_320px] flex-col gap-3.5">
            {isAdmin && (
              <form
                data-coach="memory-teach"
                className="card rise flex flex-col gap-3.5 p-5"
                onSubmit={(e) => {
                  e.preventDefault();
                  void add();
                }}
              >
                <h2 className="font-display text-[17px] font-semibold">Teach it something</h2>
                <TextArea
                  label="What should they remember?"
                  value={draft}
                  onChange={setDraft}
                  placeholder="Refunds over ₹5,000 need a manager's OK."
                />
                <Select
                  label="Kind"
                  value={kind}
                  onChange={setKind}
                  options={[
                    { value: "fact", label: "A fact about the company" },
                    { value: "correction", label: "A correction to a past mistake" },
                  ]}
                />
                <Button type="submit" disabled={!draft.trim()}>
                  Remember
                </Button>
              </form>
            )}

            {/* The technical detail (embedding model, dimensions) stays
                out of sight unless someone opens it; what matters is
                whether search can find everything. */}
            <section className="card rise flex flex-col gap-3 bg-sunken p-5" style={{ animationDelay: ".08s" }}>
              <h2 className="text-sm font-semibold text-muted">Search health</h2>
              {config.memories_needing_reembedding > 0 ? (
                <div className="flex flex-wrap items-center gap-2.5 text-[13px] text-ask-text">
                  <Icon name="warn" size={16} />
                  {config.memories_needing_reembedding} memories can't be found by meaning until they are refreshed.
                  {isAdmin && (
                    <Button size="sm" variant="ghost" onClick={() => void reembed()}>
                      Refresh now
                    </Button>
                  )}
                </div>
              ) : (
                <div className="flex items-center gap-2 text-[13px] text-ok-text">
                  <span className="h-[7px] w-[7px] rounded-full bg-ok" />
                  Every memory can be found.
                </div>
              )}
              <details className="text-xs text-dim">
                <summary className="cursor-pointer hover:text-muted">Technical details</summary>
                <dl className="mt-2 grid grid-cols-3 gap-2.5">
                  <div>
                    <dt>Provider</dt>
                    <dd className="truncate font-mono text-[13px] text-muted">{config.provider_key}</dd>
                  </div>
                  <div>
                    <dt>Model</dt>
                    <dd className="truncate font-mono text-[13px] text-muted" title={config.model}>{config.model}</dd>
                  </div>
                  <div>
                    <dt>Dimensions</dt>
                    <dd className="font-mono text-[13px] text-muted">{config.dim}</dd>
                  </div>
                </dl>
              </details>
            </section>
          </div>
        </div>
      </PageBody>
    </>
  );
}

function MemoryCard({
  content,
  kind,
  meta,
  index,
  onForget,
}: {
  content: ReactNode;
  kind: string;
  meta: ReactNode;
  index: number;
  onForget?: () => void;
}) {
  return (
    <article
      className="card lift rise flex flex-col gap-2.5 px-[18px] py-4"
      style={{ animationDelay: `${Math.min(index, 8) * 0.05}s` }}
      data-coach="memory-list"
    >
      <p className="whitespace-pre-wrap text-[15px] leading-relaxed">{content}</p>
      <div className="flex flex-wrap items-center gap-2 text-xs">
{/* "fact" is the usual kind, so only the others get a tag. */}
        {kind !== "fact" && (
                  <Chip tone={KIND_TONE[kind] ?? "mute"} dot={false}>
          {kind}
        </Chip>
        )}
        {meta}
        {onForget && (
          <Button size="sm" variant="ghost" className="ml-auto" onClick={onForget}>
            Forget
          </Button>
        )}
      </div>
    </article>
  );
}

/** Marks the search words inside a hit, so you can see why it matched. */
function Highlight({ text, term }: { text: string; term: string }) {
  const words = term
    .split(/\s+/)
    .filter((w) => w.length > 2)
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!words.length) return <>{text}</>;
  const pattern = new RegExp(`(${words.join("|")})`, "gi");
  return (
    <>
      {text.split(pattern).map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="rounded bg-accent-soft px-0.5 text-ink" style={{ boxShadow: "inset 0 -2px 0 var(--accent)" }}>
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}
