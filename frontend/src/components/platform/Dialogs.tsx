import { useState } from "react";
import { ApiError } from "../../lib/api";
import Modal from "../Modal";
import { Icon } from "../icons";
import { useCopy } from "./bits";
import { call, setupLinkFor, type Person } from "./api";
import { nameOf } from "./format";

/**
 * The three popups of the people screens: inviting someone, the setup
 * link that is shown once, and the "are you sure" before a suspension.
 */

function DialogBody({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3.5 p-6">
      <h3 className="text-lg font-semibold">{title}</h3>
      {children}
    </div>
  );
}

const BUTTON = "h-[42px] rounded-[10px] px-4 font-medium transition-colors disabled:opacity-60";

/** A setup link, shown once, with a copy button. */
export function LinkDialog({ name, link, onClose }: { name: string; link: string; onClose: () => void }) {
  const copy = useCopy();
  return (
    <Modal title={`Setup link for ${name}`} onClose={onClose} width={520}>
      <DialogBody title={`Setup link for ${name}`}>
        <p className="text-[13.5px] text-muted">
          Send this to them yourself. They choose their own password through it, so you never know it. It is shown only now: Baton keeps just a fingerprint of it.
        </p>
        <div className="flex h-11 items-center gap-2 rounded-[10px] bg-bg pl-3 pr-1.5">
          <code className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{link}</code>
          <button type="button" onClick={() => void copy(link, "Setup link copied.")} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-panel px-2.5 text-[13px] font-medium">
            <Icon name="copy" size={14} />
            Copy
          </button>
        </div>
        <div className="flex justify-end">
          <button type="button" onClick={onClose} className={`${BUTTON} border border-line bg-panel`}>
            Done
          </button>
        </div>
      </DialogBody>
    </Modal>
  );
}

/** Create an account for someone and hand back its setup link. */
export function InviteDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (person: { id: string; name: string; link: string }) => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await call<{ id: string; setup_token: string }>("/people", {
        email,
        full_name: name.trim() || null,
      });
      onCreated({ id: created.id, name: name.trim() || email, link: setupLinkFor(created.setup_token) });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the account.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Invite someone" onClose={onClose} width={520}>
      <form onSubmit={(e) => void submit(e)}>
        <DialogBody title="Invite someone">
          <p className="text-[13.5px] text-muted">
            This makes their account now and gives you a one-time setup link to send them. The link works for a limited time.
          </p>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium">Their name</span>
            <input className="field" value={name} onChange={(e) => setName(e.target.value)} required autoFocus autoComplete="off" />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium">Their email</span>
            <input className="field" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="off" />
          </label>
          {error && (
            <p role="alert" className="rounded-[10px] bg-bad-soft px-3 py-2 text-[13px] text-bad-text">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className={`${BUTTON} border border-line bg-panel`}>
              Cancel
            </button>
            <button type="submit" disabled={busy} className={`${BUTTON} bg-accent font-semibold text-accent-on`}>
              {busy ? "Creating…" : "Create and get the link"}
            </button>
          </div>
        </DialogBody>
      </form>
    </Modal>
  );
}

/** "Suspend Ravi Kumar?" with an optional reason that goes into the audit log. */
export function SuspendDialog({ person, onClose, onDone }: { person: Person; onClose: () => void; onDone: (updated: Person) => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const name = nameOf(person);

  async function suspend() {
    setBusy(true);
    setError(null);
    try {
      onDone(await call<Person>(`/people/${person.id}/suspend`, { reason: reason.trim() || null }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not suspend the account.");
      setBusy(false);
    }
  }

  return (
    <Modal title={`Suspend ${name}?`} onClose={onClose} width={480}>
      <DialogBody title={`Suspend ${name}?`}>
        <p className="text-[13.5px] text-muted">They won't be able to sign in until you restore them. Nothing they made is deleted.</p>
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-medium">
            Reason, for the audit log <span className="font-normal text-muted">(optional)</span>
          </span>
          <input className="field" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} autoFocus />
        </label>
        {error && (
          <p role="alert" className="rounded-[10px] bg-bad-soft px-3 py-2 text-[13px] text-bad-text">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className={`${BUTTON} border border-line bg-panel`}>
            Cancel
          </button>
          <button type="button" disabled={busy} onClick={() => void suspend()} className={`${BUTTON} bg-bad font-semibold text-bad-on`}>
            {busy ? "Suspending…" : "Suspend"}
          </button>
        </div>
      </DialogBody>
    </Modal>
  );
}
