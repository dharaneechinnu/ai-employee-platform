import { useEffect, useState } from "react";
import { Badge, Button, Card, Empty, ErrorNote, Input, Spinner, TextArea } from "../components/ui";
import { ApiError, api, type EmbeddingConfig, type MemoryItem } from "../lib/api";
import { useAuth, useIsAdmin } from "../lib/auth";

interface SearchHit {
  id: string;
  content: string;
  score: number;
  matched_by: string;
}

/**
 * Phase 6. Search is hybrid: meaning plus keyword. Each hit reports
 * which half found it, which matters because a vector model is weak
 * on exact strings like error codes and file names.
 */
export default function Memory() {
  const { org } = useAuth();
  const isAdmin = useIsAdmin();

  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [config, setConfig] = useState<EmbeddingConfig | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

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
    setError(null);
    try {
      setHits(await api.post<SearchHit[]>(`/orgs/${org.id}/memory/search`, { query }));
    } catch (err) {
      // A mismatch between embedding models is surfaced, never papered
      // over: searching across two models returns confident nonsense.
      setError(err instanceof ApiError ? err.message : "Search failed.");
      setHits(null);
    }
  }

  async function add() {
    if (!org || !draft.trim()) return;
    await api.post(`/orgs/${org.id}/memory`, { content: draft });
    setDraft("");
    await load();
  }

  async function reembed() {
    if (!org) return;
    await api.post(`/orgs/${org.id}/embedding-config/reembed`);
    setError(null);
    await load();
  }

  if (!items || !config) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg">Memory</h1>
        <Badge tone="gray">{config.provider_key}</Badge>
        {config.memories_needing_reembedding > 0 && (
          <Badge tone="amber">{config.memories_needing_reembedding} need re-embedding</Badge>
        )}
        {isAdmin && config.memories_needing_reembedding > 0 && (
          <Button variant="ghost" onClick={() => void reembed()}>
            Re-embed now
          </Button>
        )}
      </div>

      <Card>
        <form onSubmit={search} className="flex items-end gap-2">
          <div className="flex-1">
            <Input label="Search" value={query} onChange={setQuery} placeholder="ERR_4021" />
          </div>
          <Button type="submit">Search</Button>
        </form>
      </Card>

      <ErrorNote message={error} />

      {hits && (
        <Card className="space-y-2">
          <p className="text-xs text-neutral-500">{hits.length} result(s)</p>
          {hits.map((hit) => (
            <div key={hit.id} className="flex items-start gap-2 text-sm">
              <Badge tone={hit.matched_by === "both" ? "green" : "gray"}>{hit.matched_by}</Badge>
              <span className="flex-1">{hit.content}</span>
            </div>
          ))}
        </Card>
      )}

      {isAdmin && (
        <Card className="space-y-2">
          <TextArea
            label="Teach it something"
            value={draft}
            onChange={setDraft}
            placeholder="We always use tabs, never spaces."
          />
          <Button onClick={() => void add()} disabled={!draft.trim()}>
            Save
          </Button>
        </Card>
      )}

      {items.length === 0 ? (
        <Empty message="Nothing remembered yet." />
      ) : (
        <Card className="space-y-2">
          {items.map((item) => (
            <div
              key={item.id}
              className="flex items-start gap-2 border-b border-neutral-800 py-2 text-sm last:border-0"
            >
              <Badge tone="gray">{item.kind}</Badge>
              <span className="flex-1">{item.content}</span>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}
