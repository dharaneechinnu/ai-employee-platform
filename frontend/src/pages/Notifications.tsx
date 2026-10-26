import { useEffect, useState } from "react";
import { Icon } from "../components/icons";
import { Button, Chip, ErrorNote, Input, PageBody, PageHeader, Spinner, Switch, useToast } from "../components/ui";
import { ApiError, api, type NotificationSettings } from "../lib/api";

/**
 * Where you hear about your runs: an email to you, and optionally a
 * Slack channel. Both carry Approve and Reject buttons, so a paused
 * run does not wait for you to open the app.
 */

type EventKey = "on_approval_requested";

const EVENTS: { key: EventKey; title: string; who: string }[] = [
  { key: "on_approval_requested", title: "An action needs approval", who: "With Approve and Reject buttons right in the message" },
];

export default function Notifications() {
  const toast = useToast();
  const [settings, setSettings] = useState<NotificationSettings | null>(null);
  const [webhook, setWebhook] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    void api.get<NotificationSettings>(`/me/notifications`).then(setSettings);
  }, ["me"]);

  async function save(next: Partial<NotificationSettings> & { slack_webhook_url?: string; clear_slack_webhook?: boolean }) {
    if (!settings) return;
    setError(null);
    setSaving(true);
    try {
      const merged = { ...settings, ...next };
      const saved = await api.put<NotificationSettings>(`/me/notifications`, {
        email_enabled: merged.email_enabled,
        slack_enabled: merged.slack_enabled,
        on_approval_requested: merged.on_approval_requested,
        slack_webhook_url: next.slack_webhook_url ?? null,
        clear_slack_webhook: next.clear_slack_webhook ?? false,
      });
      setSettings(saved);
      return saved;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save that.");
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function addWebhook(e: React.FormEvent) {
    e.preventDefault();
    const saved = await save({ slack_enabled: true, slack_webhook_url: webhook.trim() });
    if (saved) {
      setWebhook("");
      toast("Slack connected. Send a test to see it arrive.");
    }
  }

  async function sendTest() {
    setTesting(true);
    try {
      const result = await api.post<{ email: string; slack: string }>(`/me/notifications/test`);
      const failed = [result.email, result.slack].some((r) => r.startsWith("failed") || r.startsWith("unavailable"));
      toast(`Email: ${result.email}. Slack: ${result.slack}.`, failed ? "bad" : "ok");
    } finally {
      setTesting(false);
    }
  }

  if (!settings) {
    return (
      <>
        <PageHeader crumb="Settings" title="Notifications" />
        <Spinner />
      </>
    );
  }

  return (
    <>
      <PageHeader crumb="Settings" title="Notifications">
        <Button variant="ghost" icon="bell" disabled={testing} onClick={() => void sendTest()}>
          {testing ? "Sending…" : "Send a test"}
        </Button>
      </PageHeader>

      <PageBody>
        <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(380px,100%),1fr))]">
          <section className="card rise flex flex-col gap-4 p-5" data-coach="notify-channels">
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent-soft text-accent-text">
                <Icon name="mail" size={20} />
              </span>
              <div className="flex-1">
                <h2 className="font-display text-lg font-semibold">Email</h2>
                <p className="text-[13px] text-muted">Approve or reject straight from the inbox.</p>
              </div>
              {/* Shown off, and locked, while there is no mail server:
                  an "on" switch that sends nothing is a broken promise. */}
              <Switch
                checked={settings.email_enabled && settings.email_available}
                disabled={saving || !settings.email_available}
                onChange={(on) => void save({ email_enabled: on })}
                label={settings.email_available ? "Email notifications" : "Email notifications (not available yet)"}
              />
            </div>
            {!settings.email_available && (
              <div className="flex gap-2.5 rounded-xl bg-ask-soft px-3.5 py-3 text-[13px] leading-normal">
                <Icon name="warn" className="text-ask-text" />
                <span>Email approvals are not available on this server, so no email will be sent. Approval requests still appear in the app and in its bell, and Slack works without email.</span>
              </div>
            )}
            <p className="text-[13px] leading-relaxed text-dim">
              You get your own link. Opening it shows the full action; nothing is decided until you press a button.
              Links expire with the request, after 24 hours.
            </p>
          </section>

          <section className="card rise flex flex-col gap-4 p-5" style={{ animationDelay: ".07s" }}>
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 items-center justify-center rounded-xl font-display text-lg font-bold text-white" style={{ background: "linear-gradient(135deg,#36C5F0,#2EB67D 35%,#ECB22E 65%,#E01E5A)" }}>
                #
              </span>
              <div className="flex-1">
                <h2 className="font-display text-lg font-semibold">Slack</h2>
                <p className="text-[13px] text-muted">Post to a Slack channel you already watch.</p>
              </div>
              {settings.slack_connected && (
                <Switch checked={settings.slack_enabled} disabled={saving} onChange={(on) => void save({ slack_enabled: on })} label="Slack notifications" />
              )}
            </div>

            {settings.slack_connected ? (
              <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-raised p-3.5">
                <Chip tone={settings.slack_enabled ? "ok" : "mute"}>{settings.slack_enabled ? "posting" : "paused"}</Chip>
                <span className="font-mono text-[13px] text-muted">webhook ••••{settings.slack_webhook_last4}</span>
                <Button size="sm" variant="danger-ghost" className="ml-auto" onClick={() => void save({ slack_enabled: false, clear_slack_webhook: true })}>
                  Remove
                </Button>
              </div>
            ) : null}

            <form onSubmit={addWebhook} className="flex flex-col gap-3">
              <Input
                label={settings.slack_connected ? "Replace the webhook" : "Incoming webhook URL"}
                value={webhook}
                onChange={setWebhook}
                placeholder="https://hooks.slack.com/services/…"
                mono
                autoComplete="off"
              />
              <div className="flex flex-wrap items-center gap-3">
                <Button type="submit" size="sm" variant={settings.slack_connected ? "ghost" : "brand"} disabled={!webhook.trim() || saving}>
                  {settings.slack_connected ? "Replace" : "Connect Slack"}
                </Button>
                <a
                  href="https://api.slack.com/messaging/webhooks"
                  target="_blank"
                  rel="noreferrer"
                  className="text-[13px] text-dim hover:underline"
                >
                  How do I get one?
                </a>
              </div>
            </form>
            <p className="text-[13px] leading-relaxed text-dim">
              Its buttons ask you to sign in before anything is decided.
            </p>
          </section>
        </div>

        <ErrorNote message={error} />

        <section className="card rise flex flex-col p-1.5" style={{ animationDelay: ".14s" }} data-coach="notify-when">
          <div className="flex flex-col gap-0.5 px-4 pb-1 pt-3.5">
            <h2 className="font-display text-[17px] font-semibold">Tell us when</h2>
            <p className="text-[13px] text-dim">Choose which updates reach you.</p>
          </div>
          {EVENTS.map((event) => (
            <div key={event.key} className="flex items-center gap-4 rounded-xl px-4 py-3.5 hover:bg-raised">
              <div className="flex-1">
                <div className="text-sm font-medium">{event.title}</div>
                {event.who && <div className="text-[13px] text-dim">{event.who}</div>}
              </div>
              <Switch
                checked={settings[event.key]}
                disabled={saving}
                onChange={(on) => void save({ [event.key]: on })}
                label={event.title}
              />
            </div>
          ))}
        </section>
      </PageBody>
    </>
  );
}
