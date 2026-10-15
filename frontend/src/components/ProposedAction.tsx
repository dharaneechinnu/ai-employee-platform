/**
 * Exactly what an AI Employee wants to do, as readable fields: the
 * same on the Approvals page and on the approve-from-email page.
 *
 * Every value is shown in full. You cannot meaningfully approve an
 * email whose last line is cut off.
 */

const FIELD_LABELS: Record<string, string> = {
  to: "To",
  cc: "Cc",
  bcc: "Bcc",
  subject: "Subject",
  body: "Message",
  url: "Web address",
  query: "Query",
  sql: "Query",
  title: "Title",
  summary: "Title",
  start: "Starts",
  end: "Ends",
  attendees: "Guests",
  specialist_name: "Ask",
  task: "To do",
  content: "Text",
};

function label(key: string): string {
  return FIELD_LABELS[key] ?? key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, " ");
}

function show(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "—";
  return JSON.stringify(value, null, 2);
}

export default function ProposedAction({ values }: { values: Record<string, unknown> }) {
  const entries = Object.entries(values);
  if (!entries.length) return <p className="text-sm text-muted">No details: it runs with no inputs.</p>;
  return (
    <dl className="flex flex-col gap-3 rounded-xl border border-line bg-raised p-4">
      {entries.map(([key, value]) => (
        <div key={key} className="flex flex-col gap-1">
          <dt className="text-xs font-medium text-dim">{label(key)}</dt>
          <dd className="whitespace-pre-wrap break-words text-sm leading-relaxed text-ink">{show(value)}</dd>
        </div>
      ))}
    </dl>
  );
}
