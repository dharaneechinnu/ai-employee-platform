# Demo accounts

How to get a working demo on your own machine. Nothing here is a real
credential.

Start the stack, then open <http://localhost:5173>.

```bash
docker compose up -d
```

There are two kinds of account:

- the **Platform Admin**, who creates accounts and never sees what is
  inside them;
- a **personal account**, which is one person's own assistant: their
  chats, agents, memory, keys and connected apps.

## Platform Admin — <http://localhost:5173/platform>

Creates accounts and their setup links, suspends and restores them, sets
up the shared Google and Microsoft sign-in apps, and manages the AI
provider catalog. **Cannot read anyone's content**, because no endpoint
returns it.

The local development database has this admin:

| | |
|---|---|
| Email | `admin@victopialabs.com` |
| Password | `DemoAdmin2026!` |

Email and password only. There is no second factor on this account, so
be clear about what guards it: this password alone can create and
suspend every account on the platform. What still stands is a separate
token type that a normal account's token cannot satisfy, an append-only
audit log, and the absence of any endpoint that returns anyone's
content.

If your database does not have this admin, make one (see
[Starting from an empty database](#starting-from-an-empty-database)).

## A personal account — <http://localhost:5173/login>

There is no sign-up page yet. A personal account is made by the
Platform Admin:

1. Sign in at `/platform`.
2. On **People**, enter an email, for example `asha@example.com`, and
   a name, for example `Asha Rao`. Press **Create and get setup link**.
3. Copy the link. It is shown once, works once, and expires after 72
   hours. It looks like `http://localhost:5173/login?token=...`.
4. Open it in a private window, choose a password, and you land in
   **Chat**.

The person picks their own password through the link, so the Platform
Admin never knows it and cannot sign in as them. If a link is lost,
create a new account rather than looking the old link up: only its
hash is stored.

> Databases made before the change to personal accounts may still hold
> the old company demo users (`owner@victopia.com`, `priya@victopia.com`).
> The upgrade turned each into an ordinary personal account. Keys and
> connection secrets saved before that upgrade cannot be read any more
> (see migration `0015_personal_accounts.py`), so add them again.

## Making a run succeed

A new account has no AI key, so the assistant cannot answer yet.

1. Open **AI Providers** and add a key. A free Gemini key from
   <https://aistudio.google.com/apikey> is enough.
2. Open **Memory** and add a fact, for example
   *"ERR_4021 means the payment gateway timed out. Retry once, then
   tell the customer."*
3. In **Chat**, ask *"What does ERR_4021 mean and what should I do?"*.
   The assistant uses its `recall` tool and should find the fact.

To try an agent, say in Chat *"I want an agent that summarises my
unread email every weekday at 9:00"*. The assistant shows a draft card
with a readiness check. Gmail must be connected under **Connections**
before **Create** turns on.

## Starting from an empty database

```bash
cd backend
python -m scripts.bootstrap_admin --email admin@example.com
```

This creates a Platform Admin and prints the password once (or pass
`--password` to choose one). Then create a personal account from the
Platform Admin screen, as above.

> Tests run against a **separate** database (`ai_employee_test`), so
> `make test` will not wipe any of this.
