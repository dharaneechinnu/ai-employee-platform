# Demo accounts

Everything below exists in the local development database. Nothing
here is a real credential.

Start the stack, then open <http://localhost:5173>.

```bash
docker compose up -d
```

## Platform Admin — <http://localhost:5173/platform>

Runs the product: creates companies, sets AI Employee limits, suspends
accounts. **Cannot read any customer content**, because no endpoint
returns it.

| | |
|---|---|
| Email | `admin@victopialabs.com` |
| Password | `DemoAdmin2026!` |

Email and password only. The second factor this account used to
require was removed on request, so be clear-eyed about what guards it
now: this password alone can create and suspend every company on the
platform. What still stands is a separate token type a company
admin's token cannot satisfy, an append-only audit log, and the
absence of any endpoint that returns customer content.

## Company users — <http://localhost:5173/login>

Both belong to **Victopia Labs**, which has a limit of 5 AI Employees.

| Role | Email | Password | Sees |
|---|---|---|---|
| Admin | `owner@victopia.com` | `owner-password-1234` | Everything: builds AI Employees, connects providers, sets permissions, decides approvals |
| Member | `priya@victopia.com` | `member-password-1234` | Tasks, AI Employees, Memory, Members only |

**Admin builds, Member uses.** Sign in as Priya to see the nav drop
from seven items to four; navigating straight to `/policies` redirects.

## What is already seeded

- One AI Employee, **Ravi**, created from the DevOps Helper template and active
- A Gemini provider connection, with a **placeholder key**
- Two memories, including `ERR_4021`, so hybrid search has something to find

## Making an agent run actually succeed

The seeded Gemini key is a placeholder, so a task will fail with
Google's own "API key not valid". That failure is itself useful: it
shows the adapter reaching the real API and being rejected on the
credential rather than the request shape.

For a successful run, put a real key in **Providers** (a free key from
<https://aistudio.google.com/apikey> is enough) and assign a task such
as *"What does ERR_4021 mean and what should we do?"*. Ravi has the
`recall` tool, so it should find the seeded memory.

## Re-seeding

```bash
cd backend
python -m scripts.bootstrap_admin --email you@example.com
```

Then create a company from the Platform Admin screen.

> Tests run against a **separate** database (`ai_employee_test`), so
> `make test` will not wipe any of this.
