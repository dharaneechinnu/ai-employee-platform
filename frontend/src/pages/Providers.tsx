import { useEffect, useState } from "react";
import { Badge, Button, Card, ErrorNote, Input, Spinner, statusTone } from "../components/ui";
import { ApiError, api, type ConnectedProvider, type ProviderOption } from "../lib/api";
import { useAuth } from "../lib/auth";

/**
 * Phase 3. Bring your own key: each company pays its own model costs.
 *
 * A saved key is never shown again, to anyone, so this form only ever
 * writes. The last four characters are all the UI gets back.
 */
export default function Providers() {
  const { org } = useAuth();
  const [available, setAvailable] = useState<ProviderOption[] | null>(null);
  const [connected, setConnected] = useState<ConnectedProvider[]>([]);
  const [selected, setSelected] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function load() {
    if (!org) return;
    const options = await api.get<ProviderOption[]>(`/orgs/${org.id}/providers/available`);
    setAvailable(options);
    setConnected(await api.get<ConnectedProvider[]>(`/orgs/${org.id}/providers`));
    if (!selected && options.length) setSelected(options[0].key);
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org?.id]);

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    if (!org) return;
    setError(null);
    try {
      await api.post(`/orgs/${org.id}/providers`, {
        provider_key: selected,
        api_key: apiKey,
      });
      setApiKey("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not connect that.");
    }
  }

  async function test(key: string) {
    if (!org) return;
    await api.post(`/orgs/${org.id}/providers/${key}/test`);
    await load();
  }

  async function disconnect(key: string) {
    if (!org) return;
    await api.del(`/orgs/${org.id}/providers/${key}`);
    await load();
  }

  if (!available) return <Spinner />;

  const chosen = available.find((p) => p.key === selected);

  return (
    <div className="space-y-4">
      <h1 className="text-lg">AI Providers</h1>
      <p className="text-xs text-neutral-500">
        Connect your own account. The key is encrypted and cannot be read back, by you or by us.
      </p>

      <Card>
        <form onSubmit={connect} className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs text-neutral-400">Provider</span>
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="w-full rounded border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm"
            >
              {available.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.display_name}
                </option>
              ))}
            </select>
          </label>

          {chosen?.trains_on_data && (
            <p className="rounded border border-amber-900 bg-amber-950/40 px-3 py-2 text-xs text-amber-300">
              This provider may use what you send to train its models. Fine for testing; think
              carefully before pointing it at real customer data.
            </p>
          )}

          <Input label="API key" type="password" value={apiKey} onChange={setApiKey} required />

          {chosen?.docs_url && (
            <a
              href={chosen.docs_url}
              target="_blank"
              rel="noreferrer"
              className="block text-xs text-sky-400 hover:underline"
            >
              Where do I find this key?
            </a>
          )}

          <ErrorNote message={error} />
          <Button type="submit" disabled={!apiKey}>
            Connect
          </Button>
        </form>
      </Card>

      {connected.map((provider) => (
        <Card key={provider.provider_key}>
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm">{provider.display_name}</span>
            <span className="text-xs text-neutral-600">····{provider.key_last4}</span>
            <Badge tone={statusTone(provider.status)}>{provider.status}</Badge>
            {provider.trains_on_data && <Badge tone="amber">trains on data</Badge>}
            <div className="ml-auto flex gap-2">
              <Button variant="ghost" onClick={() => void test(provider.provider_key)}>
                Test
              </Button>
              <Button variant="ghost" onClick={() => void disconnect(provider.provider_key)}>
                Remove
              </Button>
            </div>
          </div>
          {provider.last_error && (
            <p className="mt-2 text-xs text-red-400">{provider.last_error}</p>
          )}
        </Card>
      ))}
    </div>
  );
}
