# AI Employee Platform — Build Plan

*Simple English version. We add one phase at a time, after we discuss it together.*

**Last updated:** 2026-10-10
**Status:** Phase 0 ✅ · Phase 1 ✅ · Phase 2 ✅ · Phase 3 ✅ · **Phase 4 ✅ (MVP)** · Phase 5 ✅ · Phase 6 ✅ · Phase 7 ✅
Phases 8–10 stay as the roadmap.

> ⚠️ **Build order changed:** Phase 7 is written as **Phase 7 Lite** (~2 weeks, not 3) and should be built **after Phase 9**. Two reasons: Phase 9 is what proves "production grade", and Phase 7 rewrites the agent loop that passed the Phase 4 gate — so we do that only once everything else is stable. See the note inside Phase 7.

> ⚠️ **Change made in Phase 5:** the **approval system moved from Phase 7 into Phase 5.** Reason: Phase 5 adds tools that write and send. Shipping those with no approval gate is the exact risk we agreed to avoid. Phase 7 now covers LangGraph and multi-agent work only.

---

## What are we building?

A website where a normal person (not a programmer) can create an **"AI employee"**.

An AI employee is like a robot worker. You:
1. Give it a name and a job (example: "Ravi, the GitHub helper").
2. Give it tools (example: "you can read our code and open pull requests").
3. Give it a task (example: "look at bug #42 and fix it").

Then it does the work by itself. You watch it work on the screen. If the work is risky, it stops and asks a human for permission first.

**Why do people want this?**
Every team has boring work that repeats every day. Sorting bug reports. Updating customer records. Writing reply emails. A normal AI chatbot cannot do this work, because:
- It forgets everything after you close it.
- It cannot touch your real apps.
- You cannot trust it with risky actions.

Our platform fixes all three problems.

---

## The 11 phases

| Phase | Simple name | What it means in one line | Status |
|---|---|---|---|
| **0** | Build the empty house | Make the project folders and tools work, with nothing inside yet. | ✅ Agreed |
| **1** | Doors and keys | Login, users, company workspaces, and the Platform Admin area. | ✅ Agreed |
| **2** | Make an AI worker | A form where you create an AI employee and give it a name and job. | ✅ Agreed |
| **3** | Give it a brain and hands | Connect the AI model (brain) and the tools it can use (hands). | ✅ Agreed |
| **4** | 🎯 **First real worker** | One AI Employee does one real job, start to finish. **The big goal.** | ✅ Agreed |
| **5** | Outside apps **+ approvals** | Email, database, any REST API. Plus the Auto / Ask / Blocked permission system. | ✅ Agreed |
| **6** | Give it a memory | It remembers past work, so it does not repeat mistakes. | ✅ Agreed |
| **7** | Teamwork (Lite) | LangGraph, branching, parallel steps, one simple manager→specialists demo. **Build after Phase 9.** | ✅ Agreed |
| **8** | Make it not break | If something fails, it retries and recovers. | ⬜ Not yet |
| **9** | Locks and money counter | Security, and counting how much money the AI spends. | ⬜ Not yet |
| **10** | Ready for real customers | Testing, and putting it online. | ⬜ Not yet |

**Phases 0 to 4 are the most important.** At the end of Phase 4 you have a real working product. Phases 5 to 10 make it bigger and stronger.

---
---

# 🎯 What we actually build now

This project is for an **interview** — to show production-grade engineering.

So the real scope is:

| | |
|---|---|
| **We build** | Phases **0 to 4** — a working product you can demo live |
| **We keep as the roadmap** | Phases **5 to 10** — written here, not built |

**Why stop at 4?**

Finishing Phases 0–4 properly beats starting 0–10 badly. A demo where one AI Employee reliably does a real job is strong. Ten half-working features is weak.

And the roadmap itself is an asset. It shows an interviewer that you thought past the demo — that you know what security, reliability and cost tracking would need, even though you have not built them yet.

**What to say in the interview:** *"I scoped to a vertical slice that works end to end, and documented the rest with the risks named. Here is what I would build next, and why in that order."*

---
---

# 🧠 The AI brains we use (and why)

**Your situation: ₹0 budget.** So everything here is free.

## 💡 The key decision: BYOK (Bring Your Own Key)

**Each company pastes their own API key and pays their own AI bill.** You pay nothing.

| Layer | Who decides |
|---|---|
| Which providers are **supported** (the menu) | 🔑 You, the Platform Admin |
| Which provider they **use**, and the key | 👔 Each Company Admin |

This is the single decision that makes a ₹0 budget work. Full detail in [Phase 3, Part G](#part-g--provider-configuration-byok-).

**For your own development and demo**, you use your own Gemini free-tier key — just like any other company would. Below is the stack you personally use.

## Your free stack (for building and demoing)

| Job | What we use | Cost |
|---|---|---|
| **Main AI brain** (the agent loop) | **Gemini Flash** via Google AI Studio free tier | ₹0 |
| **Routine jobs** (summaries, sorting) | **Groq** free tier (runs Llama) | ₹0 |
| **Embeddings** (Phase 6 memory) | **Local** — `bge-m3` on your own computer | ₹0 **forever** |
| **Backup / testing** | **NVIDIA NIM** free | ₹0 |

**Why Gemini Flash is the right pick:** best tool-calling among the free options, a very large context window, and generous free limits. We can switch per AI Employee later if needed.

**A small clarification:** Groq and NVIDIA are not free LLMs themselves. They are free **hosting services** that run open-source models (Llama, Qwen, DeepSeek). The models are the open-source part. This means the same model can move between them.

## We build 2 adapters, not 3

| Adapter | Covers |
|---|---|
| **Gemini** | Google AI Studio (native) |
| **OpenAI-compatible** | Groq, NVIDIA NIM, Ollama, DeepSeek, OpenRouter, Together — **they all speak the same format**, so one adapter covers them all |

Less work, more providers. Switching providers is a **config change, not a code change**.

## ⚠️ Problem 1 — Rate limits will hit us

Free tiers limit **requests per minute**. And here is what people miss:

> **One task is not one request.**
> 1 task = think → tool → think → tool → … = **10 to 15 requests**

So one AI Employee task can eat a whole minute's budget.

**What we do about it:**

| Fix | Where |
|---|---|
| Redis queue — jobs wait in line instead of failing | Phase 0 (already planned) |
| Retry with waiting (backoff) | Phase 8, moved earlier if it hurts |
| "Slow mode" — one task at a time, not five at once | Phase 4 |

> This is why the queue is **not optional**. Good interview answer: *"rate limits forced a queue-based design, which is what you want for long-running agent work anyway."*

Check Google's current limits yourself — they change often.

## ⚠️ Problem 2 — Free tier may train on your data 🔒

Free tiers usually allow the provider to train on what you send. Paid tiers usually do not.

| Stage | Free tier OK? |
|---|---|
| Building and testing with fake data | ✅ **Yes, perfectly fine** |
| Your own company's real data | ⚠️ Your choice |
| **A paying customer's data** | ❌ **No** |

**The plan:** build everything free now. Before the **first real customer**, switch to a paid key. Because the provider is swappable, that is a 5-minute change.

**Why this matters:** this product touches customers' code, email and client lists. If a customer later learns their data went through a training-enabled free tier, you lose them — and you may break promises they made to *their* customers. Switching later is cheap. Getting it wrong is not.

> This is also a strong interview answer. Being asked *"what about data privacy?"* and having a real answer puts you ahead of most candidates.

---
---

# 📖 Words we must always use correctly

The word "employee" can mean two different things. That will confuse users, our team, and us. So we fix the words now, and never mix them:

| Always say this | For this | Never say |
|---|---|---|
| **AI Employee** | The robot worker 🤖 | "employee" alone |
| **Member** | A human person inside a company 🧑 | "employee" |
| **Company** (or **Organization**) | One customer business | "tenant" in the screens |
| **Platform Admin** | You, the product owner 🔑 | "super admin" |
| **Company Admin** | The customer's manager 👔 | "admin" alone |

So we say: *"Company A has 2 Members and 3 AI Employees."* Clear, no confusion.

---
---

# 🔑 Who can do what (all phases)

Three levels. The first one sits **outside** the company.

| What | 🔑 Platform Admin | 👔 Company Admin | 👤 Member | Phase |
|---|---|---|---|---|
| **Company** | | | | |
| Create a company | ✅ | ❌ | ❌ | 1 |
| Suspend / close a company | ✅ | ❌ | ❌ | 1 |
| Set the AI Employee limit | ✅ | ❌ | ❌ | 1 |
| Change company name / settings | ❌ | ✅ | ❌ | 1 |
| **People** | | | | |
| Invite a teammate | ❌ | ✅ | ❌ | 1 |
| Remove a teammate | ❌ | ✅ | ❌ | 1 |
| Change someone's role | ❌ | ✅ | ❌ | 1 |
| See the members list | ❌ | ✅ | ✅ | 1 |
| **AI Employees** | | | | |
| Create an AI Employee | ❌ | ✅ | ❌ | 2 |
| Edit instructions / settings | ❌ | ✅ | ❌ | 2 |
| Delete / archive | ❌ | ✅ | ❌ | 2 |
| Pause / activate | ❌ | ✅ | ❌ | 2 |
| Save a company template | ❌ | ✅ | ❌ | 2 |
| **AI providers (BYOK)** | | | | |
| Decide the **menu** of supported providers | ✅ | ❌ | ❌ | 3 |
| Turn a provider on / off for everyone | ✅ | ❌ | ❌ | 3 |
| **Connect a provider + paste our own key** | ❌ | ✅ | ❌ | 3 |
| Replace or remove our key | ❌ | ✅ | ❌ | 3 |
| See *whether* a company connected a provider | ✅ yes/no only | ✅ | ❌ | 3 |
| 🔒 **Read a company's API key** | ❌ **never** | ❌ never | ❌ never | — |
| **Pick** a model for an AI Employee | ❌ | ✅ from connected providers | ❌ | 3 |
| **See** the AI Employees | counts only | ✅ | ✅ | 2 |
| **Daily work** | | | | |
| Give a task to an AI Employee | ❌ | ✅ | ✅ | 4 |
| Watch a task running | ❌ | ✅ | ✅ | 4 |
| Cancel a task | ❌ | ✅ | own tasks only | 4 |
| See past task history | ❌ | ✅ | ✅ | 4 |
| **Tools and connections** | | | | |
| Connect GitHub / Gmail / database | ❌ | ✅ | ❌ | 5 |
| Disconnect an app | ❌ | ✅ | ❌ | 5 |
| 🔒 **Read a connected app's password** | ❌ **never** | ❌ never | ❌ never | — |
| **Permissions and approvals** | | | | |
| Set the **default** policy for new companies | ✅ | ❌ | ❌ | 5 |
| **Override** the policy for our own company | ❌ | ✅ | ❌ | 5 |
| Enable a 🔴 catastrophic action | ❌ **nobody can** | ❌ nobody can | ❌ nobody can | 5 |
| Approve or reject a paused action | ❌ | ✅ | ❌ | 5 |
| **Memory** | | | | |
| Choose the embedding provider + key | ❌ | ✅ | ❌ | 6 |
| Add / edit / delete memory | ❌ | ✅ | ❌ | 6 |
| Upload a document | ❌ | ✅ | ❌ | 6 |
| Search memory (via the AI) | ❌ | ✅ | ✅ | 6 |
| Set how long history is kept | ❌ | ✅ | ❌ | 6 |
| **Money** | | | | |
| See how much was spent | ✅ numbers only | ✅ | ❌ | 9 |

## The simple summary

| Role | In one line |
|---|---|
| 🔑 **Platform Admin** | Runs the product. Creates companies, sets limits. **Never sees customer content.** |
| 👔 **Company Admin** | **Builds** the AI Employees. Connects apps. Approves risky actions. |
| 👤 **Member** | **Uses** the AI Employees that already exist. Gives tasks, watches results. |

**One sentence: Admin builds. Member uses.**

## ⚠️ Two gaps we accept for now

**1. A Member can spend your money.** A Member cannot create an AI Employee, but they *can* give it tasks — and every task costs money. So a Member can raise the bill. Fix in Phase 9: a monthly spending limit per company.

**2. There is no read-only role.** Later you may want a "Viewer" — a manager who watches results but gives no tasks. Not needed now, but our permission code must be built so adding a 3rd role later is easy, not a rewrite.

---
---

# ✅ Phase 0 — Build the empty house

**Agreed on:** 2026-10-10
**Time needed:** about 2 to 4 days

## What is this phase?

Think of building a house. 🏠

Before you buy a sofa or a TV, you need the land, the walls, the electricity and the water pipes.

Phase 0 is that. We build the **empty house**. No features. Nothing a user can click. Just the base.

## Why do we do this first?

Because if the base is weak, everything we build later will break.

We want to pass one small test:

> A user opens the website → the website asks the server → the server asks the database → the answer comes back to the user.

If that small path works, we know all our pieces talk to each other correctly. Then we can start adding real things on top.

## New words you need to know

| Word | What it means in simple words |
|---|---|
| **Frontend** | The part the user sees. Buttons, screens, colours. |
| **Backend** | The hidden part. It does the thinking and saves the data. |
| **Database** | A big smart table where we keep all information forever. |
| **Docker** | A box that holds our whole app. It makes the app run the same way on your laptop and on the internet. It stops the problem of "but it works on my computer!". |
| **PostgreSQL** | The database we chose. Strong, free, and very trusted. |
| **Redis** | A waiting line (we call it a queue). AI jobs take a long time, so we put them in this line and do them one by one. |
| **FastAPI** | The backend tool. It is written in Python. It receives requests and sends back answers. |
| **React** | The frontend tool. It draws the screens the user clicks. |
| **TypeScript** | JavaScript plus safety checks. It catches mistakes before the user sees them. |
| **Tailwind CSS** | A fast way to add colours, spacing and style to screens. |
| **Migration** | A note that records one change to the database. Example: "add a new column". We keep all the notes, so we can go forward or go back safely. |
| **Alembic** | The tool that keeps these database notes for us. |
| **Test** | A small program that checks our code by itself, so a human does not have to click everything. |
| **CI** | A robot helper on the internet. Every time we save new code, it runs all the tests and tells us if we broke something. |

## What we will build

| # | Thing | Why we need it |
|---|---|---|
| 1 | Docker setup with 5 boxes: database, queue, backend, worker, frontend | So the whole app starts with **one** command |
| 2 | FastAPI backend that starts and runs | The base of all our future work |
| 3 | A tiny page called `/healthz` that answers "I am alive ✅" | Our very first test that things work |
| 4 | Database connection + the first migration | So we can save data later |
| 5 | React frontend that shows one screen | The base of all future screens |
| 6 | That screen calls `/healthz` and shows the answer | **This proves frontend + backend + database all work together** |
| 7 | Test setup, with one example test | So we can test everything from now on |
| 8 | Code checkers (ruff, mypy, eslint) | They find mistakes automatically |
| 9 | CI robot on GitHub | It runs all tests every time we save code |

## Folder structure we will create

```
ai-employee-platform/
├── docker-compose.yml      ← starts everything with one command
├── Makefile                ← short commands: make dev, make test
├── .env.example            ← example settings file
│
├── backend/                ← the Python side
│   ├── app/
│   │   ├── main.py         ← the app starts here
│   │   ├── config.py       ← settings
│   │   └── db/             ← database code
│   ├── alembic/            ← database change notes
│   └── tests/              ← tests
│
├── frontend/               ← the React side
│   └── src/
│       ├── App.tsx         ← the app starts here
│       └── components/     ← screen pieces
│
└── docs/                   ← this plan lives here
```

## What we will **NOT** build in Phase 0

This is important. In Phase 0 there is **no**:

- ❌ Login
- ❌ AI employee
- ❌ AI model
- ❌ Any real feature a customer would use

This may feel slow and boring. But it is the fastest road. Fixing a weak base later is very slow and very painful.

## Database work in this phase

Only **one** small table:

```
organizations
├── id          (a unique number)
├── name        (example: "Victopia Labs")
├── slug        (short url name, example: "victopia")
└── created_at  (the date it was made)
```

We make this table now, even though it is empty, only to prove that migrations work.

## Backend APIs in this phase

An **API** is a door on the backend. The frontend knocks on the door and gets an answer.

| Door (API) | What it does |
|---|---|
| `GET /healthz` | Answers "I am alive". Does not check the database. |
| `GET /readyz` | Answers "I am ready". This one **does** check the database and the queue. |

Why two doors? Because "I am running" and "I am ready to work" are different things. The app can be running but the database may be down.

## Frontend work in this phase

Just one simple screen:
- The page layout (header, side menu, main area)
- A small status box that shows a green ✅ or a red ❌
- It gets that answer from `/healthz`

No design beauty yet. That comes in Phase 1.

## What this phase needs from before

Nothing. This is the very first phase. 🎉

## ✅ Finish checklist — Phase 0 is done when:

- [ ] I type `docker compose up` and both the website and the server start. No extra manual steps.
- [ ] The website shows a green ✅ status, taken from the backend.
- [ ] `make test` passes on a fresh download of the code.
- [ ] The CI robot shows green on GitHub.
- [ ] Database migration can go **forward** and also **backward**. (Very important. This is how we undo a mistake.)
- [ ] The code checkers find zero problems.

**Rule: we do not start Phase 1 until every box above is ticked.**

---
---

# ✅ Phase 1 — Doors and keys

**Agreed on:** 2026-10-10
**Time needed:** about 1.5 to 2 weeks

## What is this phase?

Now we add **the front door and the keys**.

Four things:
1. **Login** — a person can come inside.
2. **Users** — we remember who each person is.
3. **Workspaces** — each company gets its own private room.
4. **Platform Admin area** — your own private control room, where you create companies and watch the health of the product.

## Decisions you made for this phase

| Topic | Decision |
|---|---|
| Login type | Email + password only. No Google login for now. |
| Roles inside a company | Only 2: **admin** and **member** |
| Invite emails | No email service. The invite link is shown on screen; you send it yourself. |
| Theme | **Dark theme** |
| Who creates companies | **Only the Platform Admin.** There is no public sign-up page. |
| Approval queue | **None.** The company is Active the moment you create it. |
| Can Platform Admin read customer content? | **No. Never.** (Option "a") |
| 2FA for Platform Admin | **Yes, compulsory** |
| Employee limit per company | **Yes.** Platform Admin sets how many AI employees each company may create. |

---

## Part A — The private room idea (multi-tenancy)

This is the most important idea in Phase 1. Please read it slowly. 🙏

Our website is used by **many companies at the same time**. Company A and Company B share the same website and the same database.

So we must be 100% sure **Company A can never see Company B's data**.

Think of an apartment building: 🏢
- One building = our website
- Many families inside = many companies
- Every family has their own lock
- No family can walk into another family's room

The technical name is **multi-tenancy**. One "tenant" = one company.

**How we do it:** every table in the database gets a column called `org_id`. It says "this row belongs to company number 5."

**Why now and not later:** adding this column now, while the database is empty, is easy. Adding it later, after 50 tables hold real customer data, is slow and risky — we could mix up two companies' data by mistake. That is the worst possible bug for this kind of product. So we pay the small cost now.

### The 404 trick 🕵️

When Company A tries to open Company B's page, most websites answer:

> ❌ **403 — You are not allowed**

But this leaks a secret. It tells the attacker *"this page exists, you just can't see it."*

So we answer instead:

> ✅ **404 — This does not exist**

Now the attacker learns nothing. Small change, much safer.

---

## Part B — Two kinds of admin ⚠️

We now have **two** different admins. They sound the same but are completely different:

| | **Company Admin** | **Platform Admin** |
|---|---|---|
| Who? | Our customer's manager | **You.** The product owner. |
| Controls | Only their own company | The whole website |
| How many? | Many | Very few (1 to 3) |
| Logs in where? | The normal website | A **separate** admin area |

**The golden rule:**

> A Company Admin must **never** be able to become a Platform Admin.

So Platform Admin is **not** a role in the normal roles list. It lives in a **separate table**, with a **separate login area**. Two separate systems. A bug in company roles can then never leak master access.

Like a hotel: 🏨 a guest can be the VIP of room 301, but a VIP guest can never become the hotel manager. Different job, different key, different door.

---

## Part C — What the Platform Admin can and cannot see 🔒

**The rule in one line:**

> Platform Admin sees **how much** and **how healthy**. Never **what**.

### ✅ CAN see — counting and health only

| Thing | Example |
|---|---|
| Company name and created date | "Victopia Labs, created 10 Oct" |
| Number of users | "8 users" |
| Number of AI employees | "3 AI employees" |
| Number of tasks run | "240 tasks this month" |
| Pass and fail counts | "212 passed, 28 failed" |
| Error **types** only | "20 timeout, 8 bad login" |
| Money spent | "$43 this month" |
| Which apps are connected | "GitHub ✅, Gmail ✅" |
| Last active time | "2 hours ago" |
| Active or suspended | "Active" |

### ❌ CANNOT see — real customer content

| Thing | Why not |
|---|---|
| Email text | Their private business |
| Code and files | Their private business |
| Customer records (CRM) | May hold other people's personal data |
| The task the user typed | May name real clients |
| What the AI wrote back | Same reason |
| The AI's memory content | Same reason |
| Passwords and API keys | **Never. Not even encrypted.** |

### How we make this real, not just a promise

A promise in a document is easy to break by accident. So we enforce it in the code:

| Rule | What it does |
|---|---|
| 1. Separate table + separate login area | A company-role bug can never leak master access |
| 2. 2FA compulsory for Platform Admin | A password alone is not enough for a master key |
| 3. Every Platform Admin action goes in a diary | We always know who did what, and when |
| 4. Platform Admin **cannot** edit or delete that diary | Otherwise the diary is worthless |
| 5. Every database column is marked "confidential" or "not" | The admin API is only allowed to read the "not confidential" ones |
| 6. A test proves rule 5 | If someone later marks email text as "not confidential", the test fails and blocks it |

### Why we are this careful

Honest reason: a Platform Admin account is a **master key** to the whole business. If that one password is stolen *and* that account can read customer content, then **every customer's private data leaks at once**. For a product touching people's code, email and customer lists, that is the kind of event a company does not recover from.

So: the Platform Admin simply does not have the ability. Not "has it but is told not to use it".

### For customer support (decided: option "a")

A customer calls: *"My AI employee keeps failing!"* You can see *"28 failures, type: timeout"* but not the task content.

**What you do:** ask the customer to copy-paste the details to you.

**Why this is good for now:** you will have few customers at the start, so this is easy. And *"we technically cannot read your data"* is a very strong, very simple promise for a new customer.

**Later (Phase 9)** we may add "break glass": you click *request access*, the **customer clicks Approve**, you see their data for **1 hour only**, and the whole thing is written in the diary. Good support, still honest. Not needed on day one.

---

## Part D — How a new company gets created

There is **no public sign-up page**. Nobody can create an account alone.

```
You (Platform Admin)
  → click "Add Company"
  → type the company name + the first person's email
  → system creates the company (Active immediately)
    and makes a one-time invite link
  → you copy the link and send it on WhatsApp / Slack
  → the person clicks, sets their password, starts working right away
```

A company has 3 states:

| State | Meaning |
|---|---|
| **Active** | Everything works normally |
| **Suspended** | You paused them (example: no payment). They can log in but cannot run AI employees. |
| **Closed** | Finished and gone |

There is no "Pending" state, because the company only exists after you create it.

### Employee limit (the quota) 🔢

Every company has a limit on **how many AI employees it can create**. You control this number.

| | |
|---|---|
| Where it is saved | A column `max_employees` on the company |
| Who sets it | **Only the Platform Admin** |
| When | You type it when creating the company. You can change it any time after. |
| Default | 3 (we can change this default) |
| What happens at the limit | The company sees: *"You have reached your limit of 3 AI employees. Contact support to increase it."* |
| What counts | Only live employees (draft, active, paused). **Archived ones do not count.** |

**Why this matters:** each AI employee spends real money (AI model calls). This limit is how you stop one company from costing you more than they pay. Later it becomes your paid plans — Free = 3, Pro = 10, and so on.

**Where it is checked:** the limit is **stored** in Phase 1, but **enforced** in Phase 2, because that is when employees can actually be created. The check must be in the backend, not only the screen — otherwise someone could bypass it by calling the API directly.

---

## Part E — ⚠️ One honest timing problem

You asked for an admin page showing **company data and activity**.

But in Phase 1 **there is no activity yet.** No AI employees, no tasks, no costs exist until Phase 4. An activity dashboard built now would just show zeros.

So we split it in two:

| Part | What we build | When |
|---|---|---|
| **Part 1** | Platform Admin login, 2FA, separate table, the diary, company list, Add / Suspend / Close buttons, basic counts (companies, users) | **Now, Phase 1** ✅ |
| **Part 2** | Full activity dashboard: tasks, pass rate, money spent, error types, charts | **Later, Phase 9** |

This way you get the important thing — **control of the gate** — immediately. The charts come when there is real data to put in them.

---

## New words you need to know

| Word | Simple meaning |
|---|---|
| **User** | One person with an account |
| **Organization** (org / workspace) | One company. A private room in the building. |
| **Membership** | The link between a person and a company. "Ravi is in Victopia Labs, as an admin." |
| **Role** | What a person is allowed to do |
| **Hashing** | We never save your real password. We turn it into strange letters that cannot be turned back. So a thief who steals our database still cannot read anyone's password. |
| **Token** | A temporary paper ticket. After login you show the ticket, not your password, on every request. |
| **Access token** | The short ticket. Works ~15 minutes only. Short on purpose — a stolen one dies fast. |
| **Refresh token** | The long ticket. It quietly gets you new short tickets, so you do not log in every 15 minutes. |
| **2FA** | Two Factor Authentication. Password **plus** a 6-digit code from an app on your phone. |
| **RBAC** | "Role based access control". Just means: your role decides what you can do. |
| **MSW** | A fake backend. It lets us build and click the screens **before** the real backend is ready. |
| **Audit log** | The diary. A list of important actions that nobody can edit. |

---

## Database work in this phase

**Normal tables:**

| Table | What it holds |
|---|---|
| `users` | email, hashed password, name |
| `organizations` | company name, slug, **status** (active / suspended / closed), **`max_employees`** (the limit) |
| `memberships` | which person is in which company + role (admin / member) |
| `invitations` | the one-time invite code, who it is for, expiry date |
| `refresh_tokens` | the long tickets, so we can cancel them if stolen |
| `audit_log` | the company-level diary |

**Platform Admin tables — kept separate on purpose:**

| Table | What it holds |
|---|---|
| `platform_admins` | your admin accounts, with 2FA secret |
| `platform_admin_audit` | the master diary. **Append only** — nothing can be edited or deleted. |

---

## Backend doors (APIs) in this phase

**Normal user doors:**

| Door | What it does |
|---|---|
| `POST /auth/accept-invite` | Use an invite link, set a password, create the account |
| `POST /auth/login` | Log in, get tickets |
| `POST /auth/refresh` | Get a new short ticket |
| `POST /auth/logout` | Throw away the tickets |
| `GET /auth/me` | "Who am I?" |
| `GET /orgs` | List my companies |
| `GET /orgs/{id}/members` | Who is in this company |
| `POST /orgs/{id}/invites` | Company admin invites a teammate |
| `PATCH /orgs/{id}/members/{user}` | Change someone's role |

> Note: there is **no** `POST /auth/register`. Accounts can only be made from an invite link.

**Platform Admin doors — separate path, separate login:**

| Door | What it does |
|---|---|
| `POST /platform/auth/login` | Admin login (password + 2FA code) |
| `POST /platform/companies` | Create a company + set its employee limit + get its first invite link |
| `GET /platform/companies` | List all companies with safe counts only (includes "3 of 5 employees used") |
| `PATCH /platform/companies/{id}/limits` | Change the employee limit |
| `POST /platform/companies/{id}/suspend` | Pause a company |
| `POST /platform/companies/{id}/reactivate` | Un-pause a company |
| `POST /platform/companies/{id}/close` | Close a company |
| `GET /platform/audit` | Read the master diary |

---

## Frontend screens in this phase

**Customer side (dark theme):**
1. **Login** page
2. **Accept invite** page (set your password)
3. **Company switcher** — a dropdown at the top
4. **Members page** — table of people and their roles
5. **Invite teammate** form — shows the link to copy
6. **Protected pages** — not logged in? go back to login

**Platform Admin side (separate area):**
7. **Admin login** with 2FA
8. **Companies list** — with Add / Suspend / Close buttons, and each row shows "3 of 5 employees used"
9. **Add company** form — set name, first user's email, **employee limit**; shows the invite link to copy
9b. **Edit limit** — a small box to change a company's employee limit
10. **Diary viewer** — the master audit log

We build all screens with the **fake backend (MSW)** first, so you can click and see everything before the real backend is done. Then we switch to the real backend.

### Design direction

- **Dark theme** as the base
- Clean and simple. Readable text. Good spacing.
- The Platform Admin area will look **clearly different** from the customer area (different accent colour), so you never get confused about which one you are in. This is a safety feature, not decoration.

---

## What this phase needs from before

Phase 0 must be finished ✅

---

## ✅ Finish checklist — Phase 1 is done when:

**Customer side:**
- [ ] I can: open an invite link → set password → log in → see my company → invite a teammate → switch companies
- [ ] 🔒 A user from Company A gets **404** on every single Company B page. One test per door proves it.
- [ ] 🔒 The safety test passes: no table forgot `org_id`
- [ ] Every door checks the role. A test proves no door was left open by mistake.
- [ ] If a thief copies an old long ticket, **all** of that user's tickets die immediately
- [ ] The frontend works fully on the fake backend, with the real backend switched off

**Platform Admin side:**
- [ ] I can log in with password + 2FA. Without the 2FA code, login fails.
- [ ] I can create a company, set its employee limit, and get an invite link
- [ ] I can change a company's employee limit later
- [ ] The company list shows "x of y employees used"
- [ ] I can suspend a company, and then its users cannot run anything
- [ ] 🔒 **A Company Admin cannot reach any `/platform/*` door.** Tested on every one.
- [ ] 🔒 **A Platform Admin cannot read customer content.** A test tries to read email text, task text and credentials through the admin API, and all attempts fail.
- [ ] 🔒 Every admin action appears in the diary, and the diary cannot be edited or deleted
- [ ] The admin area looks visibly different from the customer area

**Rule: we do not start Phase 2 until every box above is ticked.**

---
---

# ✅ Phase 2 — Make an AI worker

**Agreed on:** 2026-10-10
**Time needed:** about 1 to 1.5 weeks

## What is this phase?

We build the **form where a Company Admin creates an AI Employee**.

They fill in: name, job, instructions, which AI brain, which tools. Then they click **Save**.

## ⚠️ There is NO AI in Phase 2

This feels strange, so let me explain clearly.

In Phase 2 the AI Employee **cannot do anything yet**. It just sits saved in the database. It is only **settings on paper**.

Think of hiring a real person. 🧑‍💼 First you write the job description — name, title, duties, tools. You write it **before** the person starts work.

| Phase | What it is |
|---|---|
| **2** | Writing the job description |
| **3** | Giving them a brain and hands |
| **4** | They do their first real job |

**Why this order?** The form is cheap and easy to build. Once it exists, Phases 3 and 4 become much clearer — we have a real thing to point at and say *"make this one work."*

## Decisions you made for this phase

| Topic | Decision |
|---|---|
| Instructions box | **Guided questions**, plus an "Advanced" link to the raw text box |
| Version history | **Yes** |
| Platform templates | **All 5**: DevOps, Support, Data, Sales, HR |
| Company's own templates | **Yes** — a Company Admin can save their own template |
| Who can create an AI Employee | **Company Admin only** |
| Department field | **Yes**, but optional to fill |
| Employee limit | **Enforced here** (the number was set in Phase 1) |

---

## Part A — What is inside an AI Employee?

| Setting | Simple meaning | Example |
|---|---|---|
| **Name** | What you call it | "Bug Fixer Bot" |
| **Photo** | A small picture or letter icon | 🤖 |
| **Job title** | Its role | "GitHub Helper" |
| **Department** | Which team it belongs to (optional) | "Engineering" |
| **Instructions** | The most important part. How it should behave. | "You are careful. You read the bug first. You never delete code. You always explain what you did." |
| **Model** | Which AI brain to use. ⚠️ In Phase 2 this is a fixed list. In **Phase 3** it becomes the real list of providers *this company connected* (BYOK). | Gemini Flash |
| **Creativity level** | How much it should freestyle. Low = careful (good for work). High = creative (good for ideas). | Low |
| **Max steps** | A safety stop. "Never take more than 15 actions for one task." | 15 |
| **Tools** | What it may touch | Read code ✅ · Open PR ✅ · Delete repo ❌ |
| **Status** | Draft / Active / Paused / Archived | Active |

### About "Max steps" — a small but important seatbelt 🛑

An AI can get confused and loop forever: *try → fail → try → fail...* Every try costs money.

So we set a limit. After 15 actions it stops and says *"I could not finish this."*

Without this limit, one confused AI Employee could run all night and cost hundreds of dollars. This is cheap insurance.

---

## Part B — Version history 📚

Please read this one carefully. It is easy to skip and painful to add later.

Imagine:

> **Monday** — You write instructions for Bug Fixer Bot.
> **Tuesday** — It does something wrong. 😠
> **Wednesday** — You edit the instructions to fix it.
> **Friday** — Your customer asks: *"Why did it do that wrong thing on Tuesday?"*

If we simply **overwrite** the old instructions, we can never answer. The old text is gone. We cannot know *why* it behaved that way.

**So instead:** every time you save an edit, we keep a frozen copy of the old one. Like version history in Google Docs.

And every task records **which version it used**. So on Friday you can say: *"On Tuesday it was running version 3, and version 3 said this..."*

**Why now?** It is almost free to build today. It is very hard to add after 5,000 saved tasks already point at settings that changed.

---

## Part C — The instructions box: guided questions 🧭

Here is the real problem we are solving.

Your users are **sales, HR and operations people**. They are not programmers. Writing good AI instructions is a **skill**.

If a sales person writes just:

> *"be helpful"*

...the AI will behave badly. Not because the AI is weak, but because the instructions were too thin. And then the user blames **your product**. 😞

**So we do not give them an empty box.** We ask small easy questions:

| We ask | They answer |
|---|---|
| What should this AI Employee do? | "Look at bug reports and fix small bugs" |
| What should it **never** do? | "Never delete code. Never touch the main branch." |
| What tone should it use? | "Short and polite" |
| When must it ask a human first? | "Before opening any pull request" |
| What does a good result look like? | "A pull request with a clear title and explanation" |

Then **we** build the proper instructions from their answers.

**Plus an "Advanced" link** that opens the raw text box, for expert users who want full control.

So beginners get guided. Experts get freedom.

> This is one of the decisions that most affects whether users love or hate the product. An empty box looks simpler, but it quietly pushes hard work onto people who do not know how to do it.

---

## Part D — Templates 📋

### Platform templates (we provide these)

| Template | What it does |
|---|---|
| 🔧 **DevOps Helper** | Reads bug reports, looks at code, opens fixes |
| 💬 **Support Agent** | Reads customer emails, writes draft replies |
| 📊 **Data Analyst** | Asks the database questions, writes reports |
| 💼 **Sales Assistant** | Updates customer records, prepares notes |
| 👥 **HR Helper** | Answers staff policy questions |

### Company templates (the Admin provides these)

A Company Admin can also **save their own template**.

Example: Ravi builds a really good "Bug Fixer Bot". He wants 3 more just like it with small changes. Instead of starting from zero each time, he clicks **Save as template**. Now it appears in *his company's* template list only.

| Rule | Why |
|---|---|
| A company template is visible **only inside that company** | 🔒 It may contain their private business rules |
| A company template can **never** become a platform template | 🔒 That would leak one customer's setup to all customers |
| We store this with `org_id` set. Platform templates have `org_id` empty. | One table, clear separation |

### How a template is different from an AI Employee

| Thing | Who makes it | What it is |
|---|---|---|
| **Template** | Us, or a Company Admin | A ready-made blank form |
| **AI Employee** | A Company Admin | The real worker, made by filling in the form |

Like a resume. 📄 We give you a resume *template*. You fill it in and it becomes *your* resume.

---

## Part E — The AI Employee limit 🔢

The limit number was set by you (Platform Admin) in Phase 1. Here is where we **enforce** it.

| Rule | Detail |
|---|---|
| When the Admin clicks Save on a new AI Employee | We count their live AI Employees first |
| If they are at the limit | Block it. Show: *"You have reached your limit of 3 AI Employees. Contact support to increase it."* |
| What counts | Draft, Active and Paused |
| What does **not** count | Archived |
| Where the check runs | **The backend.** Not only the screen. |

> ⚠️ **Why the backend matters:** if the check is only on the screen, a user could call the API directly and skip it. The screen check is for a nice message. The backend check is the real lock.

---

## Part F — The Preview button 👀

A button that shows the **exact text** the AI will receive.

**Why this matters:** without it, the AI is a black box. Something goes wrong and the user has no idea why.

With it, the user clicks **Preview**, sees the real text, spots the mistake, and fixes it themselves. It turns a mystery into something they can solve alone. This will save you a lot of support messages.

---

## New words you need to know

| Word | Simple meaning |
|---|---|
| **Instructions** (also called "system prompt") | The text we send to the AI that tells it how to behave |
| **Model** | The AI brain. Example: Gemini Flash, Claude. |
| **Creativity level** (also called "temperature") | Low = careful and predictable. High = creative and random. For work, use low. |
| **Max steps** | The most actions allowed for one task, so it cannot loop forever |
| **Version** | A frozen copy of the settings at one moment in time |
| **Template** | A ready-made blank form to start from |
| **Archive** | Hide it, but do not delete it. Does not count towards the limit. |

---

## Database work in this phase

| Table | What it holds |
|---|---|
| `ai_employees` | name, job title, department, status, `org_id` |
| `ai_employee_versions` | a **frozen copy** of the settings each time it is saved |
| `ai_employee_tools` | which tools this AI Employee may use |
| `templates` | both kinds. `org_id` empty = our platform template. `org_id` set = that company's own template. |

---

## Backend doors (APIs) in this phase

| Door | What it does |
|---|---|
| `POST /ai-employees` | Create (**checks the limit here**) |
| `GET /ai-employees` | List my company's AI Employees |
| `GET /ai-employees/{id}` | Open one |
| `PATCH /ai-employees/{id}` | Edit (this makes a new version) |
| `DELETE /ai-employees/{id}` | Archive it |
| `POST /ai-employees/{id}/activate` | Turn on |
| `POST /ai-employees/{id}/pause` | Turn off |
| `GET /ai-employees/{id}/versions` | See the history |
| `POST /ai-employees/{id}/preview-prompt` | **See the exact text the AI will get** |
| `GET /templates` | Our 5 templates + this company's own templates |
| `POST /templates` | Admin saves their own template |
| `DELETE /templates/{id}` | Admin deletes their own template |

---

## Frontend screens in this phase

1. **AI Employee list** — cards showing each one with its status, and "3 of 5 used"
2. **Create wizard** — step by step, not one scary long form:
   - Step 1: Who is it? (name, photo, job title, department)
   - Step 2: What should it do? (**the guided questions**)
   - Step 3: Which brain? (model, creativity, max steps)
   - Step 4: Which tools?
   - Step 5: Check and save
3. **Detail page** — tabs: Settings · Version history
4. **Template gallery** — our 5 templates and the company's own, clearly separated
5. **"Save as template"** button on an existing AI Employee
6. **Limit reached message** — friendly and clear, not a scary error

All in **dark theme**.

---

## What this phase needs from before

Phase 1 must be finished, because:
- an AI Employee must belong to a company (`org_id`)
- only a Company Admin may create one
- the limit number comes from the company record

---

## ✅ Finish checklist — Phase 2 is done when:

- [ ] I can create, edit, pause and archive an AI Employee in the browser
- [ ] Editing makes a **new version**, and I can still read all old versions
- [ ] The guided questions produce sensible instructions
- [ ] The "Advanced" link shows the raw text box, and edits there are kept
- [ ] The **Preview** button shows the exact text the AI will receive
- [ ] Bad settings are blocked, and the screen says exactly which field is wrong
- [ ] 🔒 At the limit, creating one more is blocked — **tested by calling the API directly, not just through the screen**
- [ ] Archiving one frees a slot; the count drops
- [ ] A platform template fills the form correctly
- [ ] An Admin can save their own template, and it appears only in their company
- [ ] 🔒 Company A cannot see Company B's AI Employees **or** Company B's templates (tested)
- [ ] 🔒 A **Member** cannot create, edit or archive an AI Employee (tested on every door)

**Rule: we do not start Phase 3 until every box above is ticked.**

---
---

# ✅ Phase 3 — Give it a brain and hands

**Agreed on:** 2026-10-10
**Time needed:** about 1.5 to 2 weeks

## What is this phase?

Finally, real AI. 🧠

We connect two things:

| Part | Simple meaning |
|---|---|
| **Brain** | The AI model (Gemini Flash). It thinks and decides. |
| **Hands** | Tools. The things it can actually touch and do. |

## Decisions you made for this phase

| Topic | Decision |
|---|---|
| Main model | **Gemini Flash** (free tier) |
| Adapters | **2**: Gemini + OpenAI-compatible (covers Groq, NVIDIA, Ollama) |
| Starter tools | **2, both 🟢 green**: `get_webpage` and `list_github_issues` |
| Live streaming | **Yes** — watch the AI think, word by word |
| Cassettes (recorded tests) | **Yes** |
| Provider menu | **Platform Admin** decides which providers are supported (Gemini, ChatGPT, Claude, Groq) |
| Whose API key | **The company's own key (BYOK).** Each Company Admin pastes their own key and pays their own bill. |

---

## Part A — Why brain and hands must be separate

This is the most important idea in the whole project. Please read slowly. 🙏

An AI model alone can **only talk**. It cannot do anything.

Ask Gemini *"what bugs are in my GitHub?"* — it cannot know. It has no eyes and no hands. It can only guess, and guessing is worse than useless.

So we give it **tools**. A tool is a small door we open for the AI:

```
Tool: "list_github_issues"
What it does: gets the bug list from GitHub
```

Now the AI can **ask us** to use that tool. We run it, and hand back the answer.

**The AI never touches GitHub directly. It asks us. We check if it is allowed. Then we do it.**

Like a manager and an assistant. 🧑‍💼 The manager says *"get me the file."* The manager does not go into the cabinet. The assistant does — and only opens the drawers they are allowed to open.

### 🔒 This is our main security wall

The AI can only do what we gave it a tool for.

If there is **no** "delete repository" tool, then deleting a repository is **impossible** — even if the AI wanted to, even if someone tricked it with a clever message.

> Remember this one. It is the strongest security idea in the design, and it is a very good interview answer.

---

## Part B — The Agent Loop (the engine)

This is the engine of your whole product. Here is a real example.

**Task:** *"Look at bug #42 and tell me what is wrong."*

```
Step 1  AI thinks: "I need to read bug #42."
        AI asks:   use tool get_issue(42)
        We run it. We return: "Login button not working on mobile"

Step 2  AI thinks: "Now I must find the login code."
        AI asks:   use tool search_code("login button")
        We run it. We return: "Found in LoginButton.tsx"

Step 3  AI thinks: "Let me read that file."
        AI asks:   use tool read_file("LoginButton.tsx")
        We run it. We return the file contents

Step 4  AI thinks: "I found it. The button is hidden on small screens."
        AI asks:   nothing
        AI answers: "The bug is on line 24. The CSS hides the button
                     below 400px width."

        ✅ Done. 4 steps.
```

The pattern: **think → ask for tool → get answer → think again.** Round and round, until it has the answer.

**That circle is the agent loop.** We build it in this phase.

---

## Part C — The safety labels: 3 kinds of tool 🚦

Not all tools are equally dangerous. So **every** tool carries a label:

| Label | Meaning | Examples | Can it be undone? |
|---|---|---|---|
| 🟢 **read** | Only looks. Changes nothing. | read a file, list bugs, search code | Nothing to undo |
| 🟡 **write** | Creates or changes something | open a pull request, write a comment, add a CRM note | Yes, usually |
| 🔴 **destructive** | Deletes or sends. **Cannot be undone.** | delete a file, send a customer email, force push | **No** |

### Why we add labels now, in Phase 3

In Phase 7 we add the rule: *a 🔴 red tool always stops and asks a human first.*

But that rule only works if **every** tool already carries its label.

If we add labels later, we must go back and check 50 tools one by one — and we will miss one. The one we miss will be the one that emails 400 customers by mistake.

**So the label is compulsory.** A tool cannot be registered without one. The code refuses to start.

**In Phase 3 we build only 🟢 green tools.** Safest possible start.

---

## Part D — Errors go back to the AI, not to a crash

A small detail that makes a huge difference in quality.

When a tool fails, there are two choices:

| Choice | What happens |
|---|---|
| ❌ Crash the task | *"Error: file not found."* Task dead. User angry. |
| ✅ Tell the AI | AI reads: *"That file does not exist."* AI thinks: *"Let me search for the correct name instead."* AI recovers and continues. |

**We always do the second.** This single decision is a big part of why some AI agents feel smart and others feel broken.

So every tool failure — timeout, 404, bad input, server error — is turned into a **plain sentence** and handed back to the AI as its next piece of information.

---

## Part E — Safety limits (the seatbelts) 🛑

| Limit | Why |
|---|---|
| **Max steps** (example: 15) | Stops a confused AI from looping forever |
| **Max tokens** per task | Stops one task from eating the whole free-tier budget |
| **Timeout per tool** (example: 30 seconds) | Stops one slow tool from freezing the whole task |
| **Max wall-clock** per task | Stops a task from running all night |

Without these, one confused AI Employee could run for hours. With a free tier, it would also block every other task behind it in the queue.

---

## Part F — Testing something that is never the same twice 🎬

A real problem: the AI gives **different answers every time**. So normal testing does not work — you cannot write *"the answer must be exactly X."*

Also, every test run costs money and eats the free-tier rate limit.

**The solution: cassettes.**

```
First run:   run the task for real → SAVE every AI reply to a file
Every run after: REPLAY from the file → no API call, no cost, instant
```

Like recording a phone call and playing it back later.

| Benefit | Why it matters to you |
|---|---|
| Tests give the same result every time | Real testing becomes possible |
| Tests cost ₹0 | Important with no budget |
| Tests run offline and fast | No rate-limit problems in CI |
| **Interview value** 🎯 | This is a senior-level technique. Very few candidates do it. Be ready to explain it. |

---

## Part G — Provider configuration: BYOK ⚙️

**BYOK** means "Bring Your Own Key". Each company brings their own AI account.

### Two layers

| Layer | Who | What they do |
|---|---|---|
| **1. The menu** | 🔑 **Platform Admin** | Decides which providers are *supported*: Gemini, ChatGPT (OpenAI), Claude (Anthropic), Groq, NVIDIA NIM |
| **2. The key** | 👔 **Company Admin** | Picks a provider from that menu, **pastes their own API key**, tests it, uses it |

**You decide what is on the menu. Each company brings their own key and pays their own bill.**

### Why BYOK is the right choice here

| Benefit | Why |
|---|---|
| 💰 **You pay ₹0** | Each company pays their own AI costs. This is the whole reason it works with no budget. |
| 📊 **No shared rate limits** | One heavy customer cannot slow down everyone else |
| 🔒 **Less risk for you** | You are not holding one key that the whole product depends on |
| 🏢 **Normal for business software** | Companies are used to this. They already have accounts. |

### What the Company Admin does

```
Company Admin
 → Settings → AI Providers
 → clicks "Connect provider"
 → picks "Google Gemini" from the menu
 → pastes their API key
 → clicks "Test"  →  ✅ Works
 → Save

Now when creating an AI Employee, "Gemini Flash" appears in the dropdown.
```

A company can connect **more than one** provider. Example: Gemini for cheap daily work, Claude for harder tasks. Then they pick per AI Employee.

### 🔒 Security rules for API keys — now much more serious

You are storing **customer API keys**. That is their money. If a key leaks, someone can spend it.

| Rule | Why |
|---|---|
| **1. Encrypted in the database** | A stolen database must not leak anyone's key |
| **2. Each company's keys get their own encryption key** (envelope encryption) | Breaking one company does not break all companies |
| **3. Write-only.** After saving, the screen shows `••••••4f2a`. There is no "show key" button, ever. | Nobody can read it back or screenshot it |
| **4. Never reaches the frontend. Never appears in logs.** | The browser must never receive a key, not once |
| **5. 🔑 The Platform Admin CANNOT read customer keys** | See below — this is the important one |
| **6. The key never enters the AI's context** | The AI gets a *handle*, not the value. So no prompt-injection trick can make the AI reveal it. |

### ⚠️ Rule 5 explained — why even YOU cannot see customer keys

> **A customer's API key is confidential customer data.**

This matches the rule we already set in Phase 1: *Platform Admin sees how much and how healthy, never what.*

So in your admin area you will see:

| You CAN see | You CANNOT see |
|---|---|
| "Company A: Gemini ✅ connected" | ❌ The key itself |
| "Company A: Claude ❌ not connected" | ❌ Any part of the key |
| "Company A: key last tested 2 hours ago, working" | ❌ Even a masked version is not sent to your screen |

**Why so strict?** If you *can* read customer keys, then one stolen Platform Admin password means every customer's AI account can be drained. By making it technically impossible, that attack simply does not exist.

### The `trains_on_data` flag ⚠️

Each provider on the menu carries a true/false flag: *does this provider train on what we send?*

| Flag | What the system does |
|---|---|
| `false` (paid tier) | Allowed for everything |
| `true` (free tier) | ⚠️ Allowed for testing with fake data. A clear warning is shown to the Company Admin. |

For BYOK this becomes a **warning to the customer**, not a block — it is their key and their choice. But they must be told clearly: *"This is a free-tier key. Your provider may use this data for training."*

> Honest and transparent beats silent. A customer who was warned and chose anyway is fine. A customer who finds out later is lost.

### What if a company has no key yet?

They cannot run any AI Employee. So:

| Where | What they see |
|---|---|
| AI Employee creation | ⚠️ *"Connect an AI provider first"* with a button that goes straight to the settings page |
| Task screen | The "Run" button is disabled, with the same message |

Clear and helpful, not a confusing error.

### Money tracking with BYOK

We still count tokens and show an **estimated** cost. But understand the limit:

- ✅ We can say *"this task used 12,400 tokens ≈ $0.004"*
- ❌ We cannot see their real provider bill

So in Phase 9 we label it clearly as **"estimated cost"**. Never pretend it is their exact bill.

### Later (not now): optional platform trial key

The `provider_configs` table has an `org_id` column:

| `org_id` | Meaning |
|---|---|
| **Filled in** | That company's own key ← **this is the normal case** |
| **Empty** | A platform key you provide (for a free trial) ← optional, later |

So if you ever want to offer *"try it for 7 days with our key"*, no redesign is needed.

> **Interview value** 🎯 — BYOK is about **unit economics**. Being able to say *"I chose BYOK so my cost per customer is zero and no customer can blow up my bill, and I built the schema so a trial key is still possible"* is a strong, senior-level answer. Most demo projects never think about who pays.

---

## Part H — ⚠️ Still no user screen in Phase 3

The loop works, but there is no nice page to run it from yet. We test it from the command line and from a small test console.

**Phase 4** connects it to real screens and real tasks.

---

## What we will build

| # | Thing | What it does |
|---|---|---|
| 1 | **Brain connector** (`LLMProvider`) | One interface, 2 adapters. Switching provider = config change. |
| 2 | **Tool shape** (`Tool`) | Every tool declares: name, description, inputs, 🚦 label, who may use it |
| 3 | **Tool registry** | The list of all tools. Each AI Employee gets only its allowed ones. |
| 4 | **The agent loop** | think → tool → think, with all limits applied |
| 5 | **2 starter tools** | `get_webpage`, `list_github_issues` — both 🟢 green |
| 6 | **Safety limits** | max steps, max tokens, tool timeout, wall-clock |
| 7 | **Error recovery** | Failures become sentences handed back to the AI |
| 8 | **Live streaming** | The AI's thinking is sent out word by word |
| 9 | **Money counter** | Every AI call records tokens and cost |
| 10 | **Cassettes** | Record and replay, for free testing |
| 11 | **Tool test console** | A small page to run one tool alone and see the result |

---

## Database work in this phase

| Table | What it holds |
|---|---|
| `llm_calls` | which model, tokens in, tokens out, cost, how long it took |
| `tool_invocations` | which tool, what inputs, what result, pass or fail, how long |
| `supported_providers` | **the menu.** Which providers exist (Gemini, ChatGPT, Claude, Groq), on/off, `trains_on_data` flag. Controlled by Platform Admin. |
| `provider_configs` | **the keys.** `org_id`, which provider, **encrypted API key**, status, last tested at. One row per company per provider. |
| `allowed_models` | which models each provider offers, the price per token, which is default |

**Why save all this?** Three reasons:
1. You can debug exactly what the AI did
2. You can count the money
3. In Phase 9 it becomes the dashboard

> Interview value: being able to show *"here is exactly what the AI did, step by step, and what it cost"* is a strong answer. Most demo projects cannot do this.

---

## Backend doors (APIs) in this phase

| Door | What it does |
|---|---|
**For everyone:**

| Door | What it does |
|---|---|
| `GET /tools` | The tool catalogue, with each tool's 🚦 label |
| `POST /tools/{name}/test` | Run one tool alone, for debugging |
| `GET /models` | The models this company can pick, **based on which providers they connected** |

**Company Admin — managing their own keys (BYOK):**

| Door | What it does |
|---|---|
| `GET /providers/available` | The menu: which providers they *could* connect |
| `GET /providers/connected` | Which they *have* connected (**masked, never the real key**) |
| `POST /providers` | Connect a provider — pick it and paste the key |
| `PATCH /providers/{id}` | Replace the key (there is no "read key") |
| `POST /providers/{id}/test` | Make one tiny call. Answer: ✅ works, or ❌ with the reason. |
| `DELETE /providers/{id}` | Disconnect |

**Platform Admin — managing the menu only:**

| Door | What it does |
|---|---|
| `GET /platform/supported-providers` | The menu list |
| `POST /platform/supported-providers` | Add a provider to the menu |
| `PATCH /platform/supported-providers/{id}` | Turn on/off, set `trains_on_data`, set allowed models |
| `GET /platform/companies/{id}/provider-status` | **Only** "Gemini ✅ / Claude ❌". 🔒 **No key data of any kind.** |

> ⚠️ Notice there is **no** Platform Admin door that returns a customer's key, not even masked. The door does not exist, so it cannot be misused.

The agent loop itself is not exposed to users yet — that is Phase 4.

---

## Frontend work in this phase

Small. Just developer helpers:

1. **Tool catalogue page** — the list of tools, grouped, with 🟢🟡🔴 badges
2. **Tool test console** — pick a tool, type inputs, see the result
3. **Tool picker** for the Phase 2 form — now it shows real tools instead of a fake list

**Company side — "Settings → AI Providers" (the main new screen):**

4. **Provider cards** — Gemini, ChatGPT, Claude, Groq. Each shows **Connected ✅** or **Not connected**.
5. **Connect form** — paste the API key, with a short "where do I get this key?" help link
6. **Test button** — ✅ Works, or ❌ with the real reason ("key is invalid", "no quota left")
7. **Masked display** — after saving, shows `••••••4f2a`. No "show" button.
8. ⚠️ **Free-tier warning** — if the provider is flagged `trains_on_data`, show: *"This provider may use your data for training."*
9. **Empty state** — if nothing is connected: *"Connect an AI provider to start"* with a clear button

**Platform Admin area (added to the Phase 1 admin screens):**

10. **Supported providers page** — the menu. On/off switch per provider, set `trains_on_data`, choose allowed models.
11. **Company provider status** — a simple list: *"Company A: Gemini ✅, Claude ❌"*. 🔒 **No keys shown, because none are sent.**

---

## New words

| Word | Simple meaning |
|---|---|
| **Tool** | A small door we open for the AI, so it can do one specific thing |
| **Tool calling** | When the AI says *"please run this tool for me"* |
| **Agent loop** | The circle: think → use tool → think → use tool → finish |
| **Token** | A piece of a word. Providers charge per token. ~750 words ≈ 1000 tokens. |
| **Provider** | The company giving us the AI brain (Google, Groq) |
| **Adapter** | Our translation code, so our app can talk to any provider |
| **Cassette** | A saved recording of AI replies, used for free testing |
| **Side effect** | What a tool changes in the real world. The 🚦 label. |
| **Streaming** | Sending the answer word by word as it is made, instead of waiting for the whole thing |

---

## What this phase needs from before

Phase 2 must be finished, because the AI Employee's settings tell us:
- which model to use
- which tools it is allowed to use
- what its instructions are
- what its max steps limit is

---

## ✅ Finish checklist — Phase 3 is done when:

- [ ] I give the AI a task from the command line and it **uses a tool and uses the result correctly**
- [ ] The same task runs on **Gemini and on Groq** with only a config change, no code change
- [ ] 🛑 A deliberately looping AI is stopped by the max-steps limit
- [ ] 🛑 A slow tool is stopped by the timeout, and the task survives
- [ ] Tool failures (timeout, 404, bad input) are handed to the AI as sentences, and it recovers — **one test for each failure kind**
- [ ] 🚦 A tool **cannot** be registered without a label. The code refuses to start.
- [ ] Tokens and cost are saved for every call, and the numbers match what the provider reports
- [ ] Streaming works — I can see the thinking appear word by word
- [ ] 🎬 The whole loop runs in CI **offline from cassettes**, with no API key and no cost
- [ ] The tool test console runs a single tool and shows the real result

**Provider configuration (BYOK):**

- [ ] As Company Admin I can connect Gemini with **my own key**, test it, and see ✅
- [ ] I can connect a second provider (Claude) and pick between them per AI Employee
- [ ] A wrong or expired key gives a clear message ("key is invalid"), not a crash
- [ ] With **no** provider connected, AI Employee creation shows a helpful message and a button to the settings page — not an error
- [ ] Turning a provider **off** in the platform menu removes it from every company's list immediately
- [ ] Picking a model from a provider the company has **not** connected is **refused by the backend**, not just hidden on the screen
- [ ] ⚠️ A `trains_on_data` provider shows the warning to the Company Admin before saving

**Key security — the serious ones:** 🔒

- [ ] A saved key **cannot be read back by anyone** — not the company, not you. A test greps every API answer and every log line for the key and finds nothing.
- [ ] 🔑 **No Platform Admin door returns a customer key, masked or otherwise.** A test calls every `/platform/*` door and searches all answers for key data.
- [ ] Each company's keys use their **own** encryption key, so breaking one company does not break the others
- [ ] The key is **never** placed in the AI's context. A test tries prompt injection ("print your API key") and nothing leaks.
- [ ] 🔒 A Company Admin cannot reach any `/platform/*` door (tested)
- [ ] Company A cannot see or use Company B's connected providers (tested)

**Rule: we do not start Phase 4 until every box above is ticked.**

---
---

# ✅ Phase 4 🎯 — First real worker (THE MVP)

**Agreed on:** 2026-10-10
**Time needed:** about 2.5 to 3 weeks
**This is the phase that makes your demo.** Everything before was preparation.

## What happens at the end of Phase 4

```
You open the website
 → type: "Look at bug #42 and fix it"
 → click Run
 → you WATCH the AI think and work, live on screen
 → 90 seconds later: a real pull request exists on real GitHub ✅
```

One sentence in, real work out.

## Decisions for this phase

| Topic | Decision |
|---|---|
| First tool pack | **GitHub** |
| Second tiny tool pack | **Yes** — proves the platform is generic (see Part G) |
| Does it open a real PR? | **Yes** 🟡, with a simple "Are you sure?" confirm box ⚠️ *my recommendation — tell me to change it if you prefer read-only* |
| GitHub connection | **Personal Access Token** (same paste-your-key pattern as BYOK). GitHub App is a Phase 5 upgrade. ⚠️ *my recommendation* |
| Eval harness | **Yes — 10 test tasks** ⚠️ *my recommendation* |
| Test repo | **We create one** with deliberately planted bugs ⚠️ *my recommendation* |
| Free-tier protection | **Slow mode** — one task at a time |

---

## Part A — Why we cannot just wait for the answer

The main new technical idea in Phase 4.

A normal website works like this:

```
Browser asks → server answers in 0.2 seconds → done ✅
```

But an AI task takes **1 to 3 minutes**. If we make the browser wait:

| Problem | What happens |
|---|---|
| Browser gives up | Most browsers time out at 30–60 seconds |
| User sees a frozen screen | They think it is broken and click again |
| One task blocks the server | Other users cannot use the site |
| Close the laptop = work lost | The task dies halfway |

**So we split it into three parts:**

```
Part 1 (fast)  Browser asks → we save the task → answer "OK, task #7 queued" → done in 0.2s
Part 2 (slow)  The WORKER picks up task #7 and does the real work
Part 3 (live)  The browser watches task #7 and sees updates appear
```

Like ordering food 🍽️ — the waiter takes your order in 10 seconds and leaves. The kitchen cooks for 20 minutes. You are not blocked while cooking happens.

| New word | Simple meaning |
|---|---|
| **Queue** | The waiting line of jobs (Redis, already set up in Phase 0) |
| **Worker** | A separate program that takes jobs from the line and does them |
| **Async** | "Not waiting." The answer comes later, not immediately. |

---

## Part B — The event log (how we remember everything)

While the AI works, many things happen. We save **every single one** as a line in a list:

```
task #7, line 1  → started
task #7, line 2  → thinking: "I need to read bug #42"
task #7, line 3  → used tool: get_issue(42)
task #7, line 4  → tool result: "Login button broken on mobile"
task #7, line 5  → thinking: "Let me find the code"
task #7, line 6  → used tool: search_code("login")
...
task #7, line 24 → finished ✅
```

**The rule: this list can only be added to. Never edited. Never deleted.**

That one rule gives us five things for free:

| Benefit | Why |
|---|---|
| 📺 **Live screen** | The browser reads new lines as they appear |
| 🔌 **Survives disconnect** | Wifi drops at line 12? On reconnect we send line 13 onward. Nothing lost. |
| 🐛 **Debugging** | Something broke? Read the exact lines. No guessing. |
| 📜 **Audit** | Proof of what the AI did, for security |
| 🔄 **Replay** | We can step through a past task later |

> **Interview value** 🎯 This is called an **append-only event log**. It is how banks and payment systems record what happened. Saying *"I used an append-only event log so any run is fully reconstructable"* is a strong senior-level answer.

---

## Part C — How the live screen works

The browser must see updates as they happen. Three ways:

| Way | How it works | Our choice |
|---|---|---|
| Polling | Browser asks "any news?" every 2 seconds | ❌ Wasteful |
| **SSE** (Server-Sent Events) | Server pushes new lines to the browser | ✅ **Yes** |
| WebSocket | Two-way live connection | ❌ Overkill — we only need one direction |

**SSE fits** because we only need server → browser. Simpler than WebSocket, works over normal HTTP.

---

## Part D — The hands: GitHub tool pack

| Tool | 🚦 | What it does |
|---|---|---|
| `get_issue` | 🟢 read | Read one bug report |
| `list_issues` | 🟢 read | List the bugs |
| `search_code` | 🟢 read | Find code by keyword |
| `read_file` | 🟢 read | Read one file |
| `comment_on_issue` | 🟡 write | Write a comment |
| `create_branch` | 🟡 write | Make a new branch |
| `commit_files` | 🟡 write | Save changed files |
| `open_pull_request` | 🟡 write | **Open the PR** ← the demo moment |

### About the 🟡 write tools

The full human-approval system is Phase 7. For the MVP we use a simpler guard:

> Before running a task that *could* write, the user ticks one confirm box: *"This task may create branches and open pull requests. Continue?"*

One checkbox. Not a workflow. Enough to stop accidents, cheap to build.

---

## Part E — ⚠️ The 80% gate (the most important rule in this plan)

At the end of Phase 4 we run **10 prepared test tasks** with automatic pass/fail checks.

> **If fewer than 8 of 10 pass, we do NOT move to Phase 5. We fix Phase 4.**

### Why this rule exists

An AI that finishes 70% of tasks is **not** 70% of a product. It is unusable:

> The user cannot tell **which** 70%.
> So they must check every result.
> But checking every result **is the work they wanted to automate.**

So 70% delivers zero value. The product only becomes useful when the user can stop checking.

### How we test something that is random every time

We cannot write "the answer must be exactly X". So each test checks a **fact**, not text:

| Test task | How we check it passed |
|---|---|
| "Fix bug #1" | Did a PR get opened? Does it change the right file? |
| "Comment on bug #2" | Does a comment now exist on issue #2? |
| "Find the login bug" | Does the answer mention `LoginButton.tsx`? |
| "Fix bug #3" — **which is impossible** | Did it **correctly say it could not do it**, instead of pretending? |

That last one matters a lot. **An AI that admits failure is better than one that fakes success.** We test for honesty, not just ability.

### The test repo

We create a small GitHub repo with **deliberately planted bugs**. Each bug has a known correct fix, so the checks can be automatic.

> **Interview value** 🎯 A measured pass rate — *"my agent passes 9 of 10 golden tasks"* — is far stronger than *"it works, let me show you."* Almost no demo project has a number.

---

## Part F — Free tier: slow mode 🐢

Remember: **1 task = 10 to 15 AI calls.** The free tier limits calls per minute.

| Setting | Value | Why |
|---|---|---|
| Tasks running at once | **1** | Stops us hitting the rate limit |
| Pause between AI calls | ~1 second | Stays inside the per-minute limit |
| On a rate-limit error | Wait and retry, do not fail | The task survives |

The queue handles this naturally — extra tasks just wait in line.

> Good interview answer: *"rate limits forced a one-at-a-time design with backoff, which is also what you want when each run costs money."*

---

## Part G — The second tiny tool pack (proving it is generic)

Your claim is *"this is a generic platform for any team."* If the demo only ever shows GitHub, an interviewer may quietly doubt that.

So we add a **very small** second pack — about 2 tools:

| Tool | 🚦 | What it does |
|---|---|---|
| `read_document` | 🟢 read | Read an uploaded document (PDF or text) |
| `answer_from_document` | 🟢 read | Answer a question using that document |

Now you can demo **two different departments on the same engine**:

```
Demo 1 — Developer AI:  "Fix bug #42"            → opens a real PR
Demo 2 — HR AI:         "What is our leave policy?" → answers from the uploaded handbook
```

**Same agent loop. Same platform. Different tools.**

> This turns "generic" from a promise into something the interviewer watched happen. Expect about 1 extra day of work.

### ⚠️ Order matters

**Build this only after GitHub passes the 80% gate.** Breadth before reliability is the trap we agreed to avoid.

---

## Part H — What happens when things crash

| Problem | What we do |
|---|---|
| Worker dies mid-task | The task does not stay stuck in "running" forever. A heartbeat expires and the task is marked failed or requeued. |
| Task runs too long | The wall-clock limit stops it |
| User clicks Cancel | The worker checks for a stop signal between steps and halts within ~5 seconds |
| Browser disconnects | The task keeps running. Reconnecting replays the missed lines. |

Full reliability work is Phase 8. This is the minimum so the MVP is not fragile.

---

## What we will build

| # | Thing | What it does |
|---|---|---|
| 1 | Task model | queued → running → done / failed / cancelled |
| 2 | Create-task door | Saves it, queues it, answers immediately |
| 3 | **Worker** | A separate program that runs the agent loop |
| 4 | **Event log** | The append-only list of everything that happened |
| 5 | **Live updates (SSE)** | Pushes new lines to the browser |
| 6 | GitHub tool pack | The 8 tools above |
| 7 | **Run timeline screen** | The star of the demo |
| 8 | Confirm box for write tools | One checkbox before a task that may write |
| 9 | Cancel button | Stops a running task |
| 10 | Crash recovery | No permanently stuck tasks |
| 11 | **Eval harness** | 10 test tasks + the pass-rate number |
| 12 | Slow mode | Free-tier protection |
| 13 | Second tiny tool pack | Proves the platform is generic |

---

## Database work

| Table | What it holds |
|---|---|
| `tasks` | what was asked, which AI Employee, **which version**, status, who asked |
| `runs` | one attempt at a task: start, end, cost, step count, error |
| `run_events` | **the append-only list.** Every think, tool call, result, error. |
| `task_heartbeats` | proof the worker is still alive, so we can spot dead ones |

> `tasks` saves **which version** of the AI Employee was used. This is where the Phase 2 version history finally pays off — you can always answer *"what instructions did it have when it did that?"*

---

## Backend doors

| Door | What it does |
|---|---|
| `POST /tasks` | Create + queue. Answers in 0.2s. |
| `GET /tasks` | My company's task list |
| `GET /tasks/{id}` | One task |
| `POST /tasks/{id}/cancel` | Stop it |
| `GET /runs/{id}` | The summary |
| `GET /runs/{id}/events` | **SSE live stream** (supports resuming from a line number) |
| `GET /runs/{id}/trace` | The full history, for debugging |

---

## Frontend screens

1. **New task** form — pick an AI Employee, type the task, tick the confirm box, Run
2. **Task list** — live status badges that update by themselves
3. **🌟 Run timeline** — the centrepiece:
   - Each step as a card: thinking / tool used / result
   - Tool inputs and outputs, collapsible
   - A live cost and step counter
   - The final answer at the bottom
4. **Cancel** button while running
5. **Document upload** (for the second tool pack)

> The run timeline is **the screen you demo**. Spend extra care here. It is what the interviewer will remember.

---

## New words

| Word | Simple meaning |
|---|---|
| **Queue** | The waiting line of jobs |
| **Worker** | The separate program that does slow jobs |
| **Async** | The answer comes later, not immediately |
| **Event log** | The add-only list of everything that happened |
| **SSE** | Server pushes updates to the browser |
| **Run** | One attempt at a task |
| **Eval harness** | A set of test tasks with automatic pass/fail checks |
| **Golden task** | One test task whose correct result we already know |
| **Heartbeat** | A regular "I am alive" signal from the worker |

---

## What this phase needs

**All of Phases 0–3.** This is the phase that joins everything together.

---

## 🎬 The demo script (practise this for the interview)

```
1. Show the AI Employee list  → "Company has 2 AI Employees"
2. Open the Developer AI      → show instructions + version history
3. Create a task              → "Look at bug #42 and fix it"
4. WATCH the timeline         → thinking, tool calls, results appearing live
5. Open GitHub                → the real pull request is there ✅
6. Show the cost counter      → "that task cost $0.004"
7. Switch to the HR AI        → ask a policy question → correct answer
8. Show the eval results      → "9 of 10 golden tasks pass"
9. Show the roadmap           → Phases 5-10, with the risks named
```

Steps 6, 8 and 9 are what separate this from a typical demo project.

---

## ✅ Finish checklist — Phase 4 is done when:

**The main journey:**
- [ ] 🎯 In a browser: create a task → watch it live → **a correct pull request exists on real GitHub**
- [ ] The second tool pack works: an HR AI answers a question from an uploaded document
- [ ] Both AI Employees run on the **same engine** with no special-case code

**Reliability:**
- [ ] 🎯 **8 or more of the 10 golden tasks pass, three runs in a row**
- [ ] Clicking Cancel stops the worker within about 5 seconds
- [ ] `docker kill` on the worker mid-task → the task does **not** stay stuck in "running"
- [ ] A task that hits max-steps ends cleanly with a clear message
- [ ] An impossible task is **correctly reported as impossible**, not faked

**Live screen:**
- [ ] Closing and reopening the browser mid-task replays the missed lines — **no gaps, no duplicates**
- [ ] The whole run can be rebuilt from `run_events` alone

**Safety:**
- [ ] A 🟡 write task cannot run without the confirm box ticked
- [ ] 🔒 Company A cannot see or cancel Company B's tasks (tested)
- [ ] 🔒 A Member can cancel their own task but not someone else's
- [ ] Cost and tokens are recorded for every task

**Free tier:**
- [ ] Five tasks queued at once run one at a time without rate-limit failures

---

🎉 **When this checklist is complete, you have a working product and a demo.**

---
---

# ✅ Phase 5 — Outside apps + the approval system

**Agreed on:** 2026-10-11
**Time needed:** about 4 weeks

## What is this phase?

Two things, and they belong together:

| Part | What it adds |
|---|---|
| **1. More hands** | Email, SQL database, and any REST API — so HR, Operations and Sales can finally use the product |
| **2. The permission system** | For every action: 🟢 Auto, 🟡 Ask a human, or 🔴 Blocked |

**Why together?** Because the new tools can **send email** and **change records**. Those must never happen silently. Tools and their permission gate ship in the same phase, or we would be shipping a danger.

## Decisions for this phase

| # | Topic | Decision |
|---|---|---|
| 1 | Policy levels | 🟢 **Auto** / 🟡 **Ask** / 🔴 **Blocked** |
| 2 | Who sets it | **Platform sets the default. Company can override it — looser or stricter.** |
| 3 | One exception | A tiny **catastrophic list** stays Blocked platform-wide (option b) |
| 4 | How precise | Per **action kind** by default (all GitHub writes), with a per-tool override when needed |
| 5 | Who approves | **Company Admin only.** Not Members. |
| 6 | If nobody approves | **Expires after 24 hours** → the task fails with a clear message |
| 7 | Approvals phase | **Moved into Phase 5** (was Phase 7) |
| 8 | Email send | **Allowed**, but the default policy is 🟡 **Ask** |
| 9 | How apps connect | **Paste a key / app password** (same as BYOK). OAuth comes later. |
| 10 | Which apps | **Email, SQL database, Generic REST.** CRM and Slack later. |
| 11 | SQL | **Read-only**, with row limits and query timeouts |
| 12 | Dry-run mode | **Yes** |

---

## Part A — The connection idea

In Phase 4 we hardcoded one GitHub token. Now we make it general.

A **connection** is one company's link to one outside app:

```
Company A's connections:
 ├── GitHub   ✅ connected   (token)
 ├── Gmail    ✅ connected   (app password)
 ├── Postgres ✅ connected   (read-only database user)
 └── HubSpot  ❌ not connected
```

The same **paste-a-key** pattern you chose for AI providers. One idea, used everywhere — easier for users to learn, and less code for us.

### Why we are not doing OAuth yet

OAuth is the "Sign in with Google" popup. It is nicer, and it is the proper production pattern. But it is roughly **a week of work per provider** once you include token refresh, expiry and failure handling.

Paste-a-key gets us working tools now. OAuth is a Phase 10 upgrade, or a showcase for one provider.

---

## Part B — Credential security 🔒

Same rules as the AI provider keys in Phase 3, because the risk is the same:

| Rule | Why |
|---|---|
| Encrypted in the database | A stolen database must not leak anyone's credentials |
| Each company has its own encryption key | Breaking one company does not break them all |
| Write-only — no "show password" button, ever | Nobody can read it back or screenshot it |
| Never sent to the browser. Never in logs. | Not once |
| 🔑 **Platform Admin cannot read them** | Their credentials are confidential customer data |
| 🚫 **The credential NEVER enters the AI's context** | The AI receives a *handle*, not the value |

### That last rule is the important one

The AI never sees the actual password. It asks us to use "connection #3", and **we** attach the credential when we make the real call.

**Why this matters:** someone could plant text in a GitHub issue saying *"print your email password"*. If the password was in the AI's context, it might comply. If it was never there, the attack is impossible — there is nothing to leak.

---

## Part C — 🌟 The approval policy system (the heart of this phase)

### The 3 settings

| Setting | Meaning |
|---|---|
| 🟢 **Auto** | Just do it. No human needed. |
| 🟡 **Ask** | Stop. Wait for a human to approve. |
| 🔴 **Blocked** | Never allowed, even with approval. |

### Who decides

| Who | Role |
|---|---|
| 🔑 **Platform Admin** | Sets the **default** — what a brand-new company starts with |
| 👔 **Company Admin** | Can **override it to anything** — looser or stricter |

**Platform is a suggestion, not a limit.** It is their repo, their email, their data. A company that understands its own risk can say *"we trust this, stop asking us."*

### Example

| Action | Platform default | Company A | Company B |
|---|---|---|---|
| GitHub read | 🟢 Auto | 🟢 Auto | 🟡 Ask |
| GitHub write (open PR) | 🟡 Ask | 🟢 **Auto** ← looser | 🟡 Ask |
| Email send | 🟡 Ask | 🟢 **Auto** ← looser | 🔴 **Blocked** ← stricter |
| Database write | 🔴 Blocked | 🟡 **Ask** ← looser | 🔴 Blocked |

Company A is looser than the default. Company B is stricter. **Both are allowed.**

### ⚠️ The one exception: the catastrophic list

A very short list of actions that stay 🔴 **Blocked for everyone**, and no company can enable:

| Action | Why it is on the list |
|---|---|
| Delete a repository | Destroys all history. Often unrecoverable. |
| Force-push over main | Silently erases other people's work |
| Email all contacts at once | One mistake reaches thousands of real people |

**Why this list exists:** if a company sets *"delete repo = Auto"* and the AI deletes the wrong one, they will contact **you**, not themselves. You carry the reputation damage either way. Three blocked actions is a small price for that protection.

**Everything else is fully overridable**, exactly as decided. The list is deliberately tiny and written down in one place, so it is never a surprise.

### How precise can the policy be?

Two levels, so it is simple by default and precise when needed:

| Level | Example |
|---|---|
| **By action kind** (the normal way) | "All GitHub 🟡 writes = Ask" — one setting covers many tools |
| **By single tool** (the override) | "...but `comment_on_issue` = Auto" — because a comment is harmless |

So a company sets 3 switches, not 30. And can still be exact where it matters.

### How "Ask" actually works

```
AI wants to: send_email
  ↓
System checks the policy  →  🟡 Ask
  ↓
Task PAUSES ⏸  (status: awaiting_approval)
  ↓
Company Admin gets a notification
  ↓
They see exactly what is proposed:
    "To: client@example.com
     Subject: Re: your invoice question
     Body: [full text shown]
     [Approve]  [Reject]"
  ↓
They click Approve ✅
  ↓
Task RESUMES ▶  and the email sends
```

**The reviewer always sees the real thing**, not a summary. You cannot approve what you cannot read.

### How we pause and resume (the hard part)

A task may wait **hours** for a human. The worker cannot sit and wait — it must move on to other jobs.

**Our method:** when a task pauses, we save the AI's conversation so far as JSON in the database. On approval, a worker loads it back and continues from that exact point.

| | This simple version (Phase 5) | LangGraph version (Phase 7) |
|---|---|---|
| Pause and resume | ✅ Works | ✅ Works |
| Survives a worker restart | ✅ Yes | ✅ Yes |
| Parallel branches | ❌ No | ✅ Yes |
| Effort | ~4 days | Already included |

This is real and it works. **Phase 7 upgrades it, rather than inventing it.**

### Approval expiry — 24 hours

If nobody answers in 24 hours, the task fails with: *"This task was cancelled because the approval request expired."*

**Why we need this:** without expiry, forgotten approvals pile up forever. Half-finished tasks hold resources and confuse everyone. Better to fail clearly and let the user retry.

---

## Part D — The new tool packs

### 📧 Email (Gmail / IMAP)

| Tool | 🚦 | Default policy |
|---|---|---|
| `list_emails` | 🟢 read | Auto |
| `read_email` | 🟢 read | Auto |
| `save_draft` | 🟡 write | Auto |
| `send_email` | 🔴 send | **Ask** |
| `delete_email` | 🔴 delete | **Blocked** |

Note `save_draft` is Auto but `send_email` is Ask. A draft nobody sends is harmless. A sent email cannot be unsent.

### 🗄️ SQL database (read-only)

| Tool | 🚦 | Default policy |
|---|---|---|
| `list_tables` | 🟢 read | Auto |
| `describe_table` | 🟢 read | Auto |
| `run_query` | 🟢 read | Auto |

**Read-only means read-only.** We enforce it three ways, not one:

| Guard | What it does |
|---|---|
| 1. A read-only database user | The database itself refuses writes. **The strongest guard.** |
| 2. Query inspection | We reject anything that is not a SELECT |
| 3. Row limit + timeout | Max 1,000 rows, 10-second timeout |

> Guard 1 is what actually protects the customer. Guards 2 and 3 give better error messages and protect against a slow query freezing their live database. Never rely on inspecting the query text alone — that is easy to trick.

### 🌐 Generic REST

One tool that connects to **almost anything** with an API. Great value for little work.

| Tool | 🚦 | Default policy |
|---|---|---|
| `http_get` | 🟢 read | Auto |
| `http_post` | 🟡 write | **Ask** |

**Safety:** the Company Admin lists which web addresses are allowed. Anything not on the list is refused. Without that, this tool could reach any site on the internet.

---

## Part E — Dry-run mode 🧪

A switch on every 🟡 write tool: *show me what you WOULD do, but do not do it.*

```
Dry run ON   →  "I would send an email to client@example.com
                 with the subject 'Re: your invoice'"
Dry run OFF  →  actually sends it
```

**Why this matters:** it is how a nervous new customer safely tries your product. They run everything in dry-run for a week, see that the decisions are sensible, then turn it off. It converts fear into trust.

---

## Part F — When outside apps misbehave

Outside apps fail, and they fail in different ways. We handle each properly:

| Problem | What we do |
|---|---|
| "Too many requests" (rate limit) | Wait and retry, with increasing pauses |
| App is down | **Circuit breaker** — after 5 failures, stop trying for 5 minutes. Fail fast instead of hanging. |
| Credential expired or revoked | Mark the connection ❌ unhealthy, tell the user plainly, do not retry forever |
| Very slow response | Timeout, and hand a clear message back to the AI |

| New word | Simple meaning |
|---|---|
| **Circuit breaker** | Like a house fuse. After repeated failures it "trips" and stops trying for a while, instead of hammering a broken service. |

---

## What we will build

| # | Thing |
|---|---|
| 1 | Connection system — add, test, remove, health status |
| 2 | Encrypted credential storage, per-company encryption keys |
| 3 | 🌟 **Policy engine** — Auto / Ask / Blocked, checked before every tool call |
| 4 | 🌟 **Approval system** — pause, notify, show the real action, approve/reject, resume |
| 5 | Approval expiry (24 hours) |
| 6 | The catastrophic blocklist |
| 7 | Email tool pack |
| 8 | SQL tool pack (read-only) |
| 9 | Generic REST tool pack with an address allowlist |
| 10 | Dry-run mode on every write tool |
| 11 | Rate limiting + circuit breakers |
| 12 | Notifications for approval requests |

---

## Database work

| Table | What it holds |
|---|---|
| `connections` | `org_id`, which app, **encrypted credential**, status, last tested |
| `policy_defaults` | the platform's starting values (set by Platform Admin) |
| `policies` | `org_id`, action kind or tool name, the chosen setting. This is the company's override. |
| `blocked_actions` | the catastrophic list. Platform-wide. No `org_id`. |
| `approvals` | which run, which tool, the proposed action in full, status, who decided, when, expires at |
| `paused_runs` | the saved AI conversation, so a paused task can resume |
| `allowed_urls` | for the Generic REST tool |

---

## Backend doors

**Connections (Company Admin):**

| Door | What it does |
|---|---|
| `GET /connections` | List ours (**credentials masked**) |
| `POST /connections` | Add one + paste the credential |
| `POST /connections/{id}/test` | Test it → ✅ or ❌ with the reason |
| `DELETE /connections/{id}` | Remove |

**Policies:**

| Door | What it does |
|---|---|
| `GET /policies` | Our settings, showing which are default and which we changed |
| `PUT /policies` | Change our settings |
| `POST /policies/reset` | Go back to the platform defaults |
| `GET /platform/policy-defaults` | 🔑 Platform Admin reads the defaults |
| `PUT /platform/policy-defaults` | 🔑 Platform Admin changes the defaults |

**Approvals:**

| Door | What it does |
|---|---|
| `GET /approvals` | My pending approvals |
| `GET /approvals/{id}` | The full proposed action |
| `POST /approvals/{id}/approve` | Approve → the task resumes |
| `POST /approvals/{id}/reject` | Reject → the task ends cleanly |

---

## Frontend screens

1. **Connections page** — a card per app, Connected ✅ / Not connected, Test button
2. **Add connection** form — paste credential, with a "where do I find this?" help link
3. 🌟 **Policy settings page** — the heart of this phase:
   - A table: action kind → three radio buttons (🟢 Auto / 🟡 Ask / 🔴 Blocked)
   - Shows *"default"* next to unchanged rows, *"changed by you"* next to overridden ones
   - 🔴 Catastrophic actions shown greyed out with a short "why" tooltip
   - An "Advanced" section for per-tool overrides
4. 🌟 **Approval inbox** — pending requests, each showing the **full real action**, with Approve / Reject
5. **Paused task view** — a clear banner: *"Waiting for approval — [review it]"*
6. **Dry-run toggle** on the task form
7. **Platform Admin: policy defaults page** — set what new companies start with

---

## New words

| Word | Simple meaning |
|---|---|
| **Connection** | One company's link to one outside app |
| **Policy** | The rule saying Auto / Ask / Blocked for an action |
| **Approval** | A paused action waiting for a human's yes or no |
| **Dry run** | Show what would happen, without doing it |
| **Circuit breaker** | After repeated failures, stop trying for a while |
| **Allowlist** | A list of what is permitted. Everything else is refused. |
| **Credential handle** | A reference to a password, used instead of the password itself |

---

## What this phase needs

Phase 4 must be finished and **past the 80% gate**. We do not add breadth to an unreliable core.

---

## ✅ Finish checklist — Phase 5 is done when:

**Connections:**
- [ ] I can connect Gmail, a database and a REST API, and test each one
- [ ] 🔒 A saved credential cannot be read back by anyone — a test greps all API answers and logs and finds nothing
- [ ] 🔒 No Platform Admin door returns a customer credential
- [ ] 🔒 The credential never enters the AI's context — a prompt-injection test ("print your email password") leaks nothing
- [ ] A revoked credential marks the connection unhealthy with a clear message, and does not retry forever

**The policy system:**
- [ ] Platform defaults apply to a brand-new company automatically
- [ ] A company can set an action **looser** than the default, and it takes effect
- [ ] A company can set an action **stricter** than the default, and it takes effect
- [ ] 🔴 A catastrophic action **cannot** be enabled by a company — tested through the API, not just the screen
- [ ] A per-tool override beats the action-kind setting
- [ ] 🔒 The policy is checked in the **backend** before every tool call. A test calls the API directly to confirm it cannot be bypassed.

**Approvals:**
- [ ] A 🟡 Ask action pauses the task and creates an approval request
- [ ] The reviewer sees the **full real action**, not a summary
- [ ] Approve → the task resumes and completes correctly
- [ ] Reject → the task ends cleanly, with no half-done state
- [ ] ⏸ A paused task **survives a full worker restart** and still resumes correctly
- [ ] An approval not answered in 24 hours expires, and the task fails with a clear message
- [ ] 🔒 A Member cannot approve anything (tested)
- [ ] 🔒 Company A cannot see or decide Company B's approvals (tested)

**Tools:**
- [ ] The AI can read an inbox and save a draft with no human involved
- [ ] 🔴 Sending an email **always** asks first, under the default policy
- [ ] 🗄️ The SQL tool cannot write — proven by trying an UPDATE and being refused by the **database user**, not only by our code
- [ ] A huge query is stopped by the row limit and the timeout
- [ ] 🌐 The REST tool refuses an address not on the allowlist
- [ ] 🧪 Dry-run shows an accurate preview and causes no real change

**Robustness:**
- [ ] A rate-limited app triggers waiting and eventual success
- [ ] A dead app trips the circuit breaker and fails fast instead of hanging

---
---

# ✅ Phase 6 — Give it a memory

**Agreed on:** 2026-10-11
**Time needed:** about 2 to 2.5 weeks

## What is this phase?

Right now your AI Employee is **amnesiac**. Every task starts from zero.

| What happens today | Why it is bad |
|---|---|
| You correct it on Monday | On Tuesday it makes the same mistake |
| It learns something useful | It forgets the moment the task ends |
| It asks you a question you already answered | Annoying, and it looks stupid |

Phase 6 gives it memory.

> ⚠️ **The trap we must avoid:** the obvious fix is "send all past history to the AI every time." That is **wrong**. It costs a fortune, it fills the context window, and it actually makes answers **worse**, because the important fact gets buried in noise. So we use three separate kinds of memory, each fetched on purpose.

## Decisions for this phase

| # | Topic | Decision |
|---|---|---|
| 6.1 | Memory types | **All three**: task notes, past-task summaries, knowledge store |
| 6.2 | Who can save memories | **Both** — the AI gets a `remember` tool, and humans can add/edit |
| 6.3 | Memory scope | **Both** available: one AI Employee only, or shared across the company |
| 6.4 | Who can edit memory | **Company Admin only** |
| 6.5 | Keep task history for | **90 days**, company-configurable |
| 6.6 | Embedding provider | **Fully configurable, same pattern as LLM providers.** Default = **Local (free)**. |

---

## Part A — First: what is an "embedding"? 🗺️

You need this word to understand the rest.

An **embedding** turns a piece of text into a long list of numbers that captures its **meaning**.

The useful property: **similar meanings get similar numbers.**

```
"dog"       →  [0.2, 0.8, 0.1, ...]
"puppy"     →  [0.2, 0.7, 0.1, ...]   ← very close to "dog"
"database"  →  [0.9, 0.1, 0.6, ...]   ← far away
```

Think of it like a **map of meaning**. 🗺️ Words and sentences get map coordinates. Things that mean similar things sit near each other.

**Why we need it:** it lets us search by **meaning**, not just matching words.

| Search type | User asks "how many holiday days do I get?" |
|---|---|
| Keyword search | Finds nothing — the document says "annual leave entitlement" |
| **Meaning search** (embeddings) | ✅ Finds it, because the meanings are close |

| New word | Simple meaning |
|---|---|
| **Embedding** | Text turned into numbers that capture meaning |
| **Vector** | The list of numbers itself |
| **pgvector** | The PostgreSQL add-on that stores and searches vectors (installed in Phase 0) |
| **Semantic search** | Searching by meaning instead of exact words |

---

## Part B — The three kinds of memory

Each solves a different problem. This is why we do not just "send everything".

### 1. 📝 Task notes (short-term)

**Lives for:** one task only. Thrown away after.
**Holds:** what the AI has figured out so far in this task.

**The problem it solves:** a long task (40 steps) produces more text than fits in the AI's context window.

**How:** when the conversation gets too big, we **compact** it — summarise the older steps into a short paragraph, keep the recent steps word-for-word.

```
Steps 1-25  →  compressed into: "Searched the codebase, found the bug
                is in LoginButton.tsx line 24, CSS media query issue"
Steps 26-30 →  kept in full detail
```

Like taking meeting minutes. You do not keep every word, you keep what matters.

### 2. 📚 Past-task summaries (episodic)

**Lives for:** 90 days (configurable).
**Holds:** a short record of each finished task.

When a task ends, we automatically save:

| Field | Example |
|---|---|
| Goal | "Fix the login bug #42" |
| What it did | "Found CSS issue, opened PR #88" |
| Result | Success ✅ |
| Lesson | "The mobile styles live in `styles/mobile/`, not the main CSS file" |

Next time, a similar task can look these up first. **This is how it stops repeating mistakes.**

### 3. 🧠 Knowledge store (semantic)

**Lives for:** forever, until deleted.
**Holds:** company knowledge the AI should always be able to look up.

| What goes in | Example |
|---|---|
| Uploaded documents | the HR handbook, API docs |
| Your corrections | "We always use tabs, not spaces" |
| Business rules | "Never contact a customer before 9am" |
| Solved problems | "When deploy fails with error X, do Y" |

This is the one that uses embeddings and search.

---

## Part C — 🌟 Embedding provider configuration

**Exactly the same pattern as the LLM providers in Phase 3.** One pattern, learned once.

```
Company Admin
 → Settings → Embedding Provider
 → picks from the menu
 → pastes their key   (not needed for Local)
 → clicks Test  →  ✅ Works
 → Save
```

| Who | Role |
|---|---|
| 🔑 **Platform Admin** | Decides which embedding providers are on the menu |
| 👔 **Company Admin** | Picks one, pastes their own key (BYOK) |

### The provider menu

| Provider | Free tier | Vector size |
|---|---|---|
| **Local** (`bge-m3`, `nomic-embed`, `gte`, `e5`, `mxbai`) ← **default** | ✅ Unlimited, no key | 1024 |
| **Jina AI** | ✅ Generous free tier | 1024 / 1536 |
| **Nomic** | ✅ Free tier | 768 |
| **Cohere** | ✅ Trial tier | 1024 |
| **Voyage AI** | ✅ Free tier | 1024 |
| **Mistral** | ✅ Free tier | 1024 |
| **Hugging Face** | ✅ Free tier | varies by model |
| **Gemini** | ✅ Free tier | 768 |
| **OpenAI** | 💰 Paid, very cheap | 1536 |

Adding a new provider later = **one adapter file.** Same as adding a tool.

### ❌ Claude is not on this list

**Anthropic has no embeddings API.** They have never shipped one. So Claude appears in the **LLM** menu only, never the embedding menu. This is not a choice we made.

### Why Local is the default

| Reason | Detail |
|---|---|
| 💰 **Cost** | Embeddings are the **highest-volume** AI call in the system — every document, every memory, every search. On a paid API this becomes the biggest bill. |
| 🚫 **No rate limits** | Removes a whole category of failure |
| 🔒 **Privacy** | Company documents never leave your server |
| ⚡ **Good enough** | `bge-m3` is genuinely competitive with paid options |

API options are offered as *"use your own provider if you prefer"* — not as the recommended path.

---

## Part D — ⚠️ The constraint that will bite us (mixing models)

> **You cannot mix embedding models. All memories must be embedded by the same model.**

Different models produce different-sized vectors in completely different "meaning spaces":

| Model | Vector size |
|---|---|
| Nomic / Gemini | 768 |
| `bge-m3` / Cohere | 1024 |
| OpenAI / Jina | 1536 |

Comparing a 768 vector to a 1536 vector is like comparing **kilograms to kilometres**.

### 🚨 Why this is dangerous

**It does not throw an error. It silently returns nonsense.**

Search still "works" — it returns results, they are just wrong. Nobody notices for weeks. That is the hardest kind of bug there is.

### How we handle it

| Rule | Why |
|---|---|
| Embedding provider is chosen **once per company** — not per AI Employee, not per memory | One meaning-space per company |
| We save the model name **with every memory row** | So a mismatch is always detectable |
| Search **refuses** to run across mixed models, with a clear error | A loud failure beats silent nonsense |
| Switching provider triggers **re-embedding everything** as a background job, with progress shown | The only correct way |
| A clear warning before switching: *"This will reprocess all 10,000 memories (~20 min). Search will be degraded until it finishes."* | No surprises |
| The database supports the common sizes (768 / 1024 / 1536), routed by the chosen model | So any provider works |

> That last row is the real engineering work in this phase. Worth doing properly, **because the failure mode is invisible.**

---

## Part E — How the AI actually uses memory

We do **not** stuff memory into every request. The AI asks for it, like any other tool:

| Tool | 🚦 | What it does |
|---|---|---|
| `recall(question)` | 🟢 read | Search memory by meaning and return the best matches |
| `remember(fact, scope)` | 🟡 write | Save something for later |

So the AI decides when memory is relevant. We do not guess for it.

### Hybrid search — why we use two methods together

| Method | Good at | Bad at |
|---|---|---|
| **Meaning search** (embeddings) | "holiday days" finding "annual leave" | Exact codes, names, IDs |
| **Keyword search** | Finding `ERR_4021` or `LoginButton.tsx` exactly | Different words, same meaning |

**So we run both and merge the results.** Meaning search alone fails badly on error codes and file names — which is exactly what a DevOps AI searches for most.

---

## Part F — Memory scope and isolation 🔒

Every memory has a scope:

| Scope | Who can see it |
|---|---|
| **AI Employee** | Only that one AI Employee |
| **Company** | All AI Employees in that company |

**The hard rule: memory NEVER crosses `org_id`.** Company A's memory is invisible to Company B, always, with no exception and no setting that can change it.

> This matters more here than anywhere else in the product. Memory holds the **most sensitive** text — business rules, customer notes, internal documents. A leak here is the worst possible leak. So we test it explicitly for every memory type, not just once.

---

## Part G — History, export and cleanup

| Feature | What it does |
|---|---|
| Searchable history | Find past tasks by date, AI Employee, status, or text |
| Compare two runs | Why did the same task work yesterday and fail today? |
| Export | Download as CSV or JSON |
| Retention | Auto-delete task history after 90 days (company-configurable) |

**Why retention matters:** without it the database grows forever, costs rise, and you hold customer data longer than you should. A configurable limit is both cheaper and more respectful.

---

## What we will build

| # | Thing |
|---|---|
| 1 | Context compaction (summarise old steps when a task gets long) |
| 2 | Automatic task summaries when a task finishes |
| 3 | Knowledge store with pgvector |
| 4 | 🌟 **Embedding provider configuration** — pluggable, BYOK, Local default |
| 5 | 🌟 **Re-embed background job** with progress, for switching provider |
| 6 | Mixed-model detection that refuses to search |
| 7 | Hybrid search (meaning + keyword, merged) |
| 8 | `recall` and `remember` tools |
| 9 | Document upload (PDF, text, Markdown) |
| 10 | Memory browser — view, edit, delete |
| 11 | History page with search, compare and export |
| 12 | Retention cleanup job |

---

## Database work

| Table | What it holds |
|---|---|
| `memories` | `org_id`, scope, type, the text, **`embedding_model`**, metadata, created date |
| `memory_vectors_768` / `_1024` / `_1536` | the vectors, one table per size, so any provider works |
| `run_summaries` | goal, actions, outcome, lesson — one per finished task |
| `embedding_configs` | `org_id`, provider, **encrypted key**, chosen model, status |
| `reembed_jobs` | progress tracking when switching provider |
| `documents` | uploaded files and their processing status |

---

## Backend doors

| Door | What it does |
|---|---|
| `GET /memory` | List our memories |
| `POST /memory` | Add one by hand |
| `PATCH /memory/{id}` | Edit |
| `DELETE /memory/{id}` | Delete |
| `POST /memory/search` | Search by meaning + keyword |
| `POST /documents` | Upload a document |
| `GET /documents/{id}` | Processing status |
| `GET /embedding-config` | Our current provider (**key masked**) |
| `PUT /embedding-config` | Change provider → **starts the re-embed job** |
| `GET /reembed-jobs/{id}` | Progress |
| `GET /runs` | History, with filters |
| `POST /runs/export` | Download CSV / JSON |
| `GET /retention-settings` · `PUT` | How long to keep history |

---

## Frontend screens

1. **Memory browser** — list, search, edit, delete. Grouped by scope.
2. **Document upload** — drag and drop, with processing progress
3. 🌟 **Embedding provider settings** — the menu, paste key, Test button
4. ⚠️ **Switch-provider warning dialog** — explains the re-embed clearly before confirming
5. **Re-embed progress bar** — *"re-processing 4,200 of 10,000..."*
6. **History page** — filters, run comparison, export button
7. **Retention settings** — a simple dropdown

---

## New words

| Word | Simple meaning |
|---|---|
| **Embedding** | Text turned into numbers that capture meaning |
| **Vector** | The list of numbers |
| **Semantic search** | Searching by meaning, not exact words |
| **Hybrid search** | Meaning search + keyword search, combined |
| **Compaction** | Summarising old steps to save space |
| **Episodic memory** | Memory of past events (finished tasks) |
| **Re-embed** | Redoing all embeddings with a different model |
| **Retention** | How long we keep data before deleting it |

---

## What this phase needs

Phase 4 (so finished tasks exist to summarise) and Phase 5 (the connection + BYOK pattern we reuse for embedding providers).

---

## ✅ Finish checklist — Phase 6 is done when:

**Memory works:**
- [ ] 🎯 I correct the AI once, and in a **later separate task** it applies that correction
- [ ] A 50-step task completes without running out of context (compaction proven)
- [ ] A finished task automatically produces a useful summary
- [ ] A similar new task finds and uses an older task's summary
- [ ] An uploaded PDF becomes searchable

**Search quality:**
- [ ] Meaning search finds "annual leave" when asked about "holiday days"
- [ ] Keyword search finds an exact error code like `ERR_4021`
- [ ] Hybrid search beats either one alone, measured on a small labelled set — **not judged by feel**

**Embedding providers:**
- [ ] Local works with **no key and no internet**
- [ ] I can switch to Jina or Gemini with my own key, and Test says ✅
- [ ] 🔒 The embedding key cannot be read back by anyone, including Platform Admin
- [ ] ⚠️ Switching provider shows the warning **before** anything changes
- [ ] 🔄 The re-embed job runs in the background with visible progress, and search still works on old data until it finishes
- [ ] 🚨 **Searching across two different embedding models is refused with a clear error** — never silently wrong. *This is the most important test in the phase.*

**Isolation and cleanup:**
- [ ] 🔒 Company A can never retrieve Company B's memory — **one explicit test per memory type**
- [ ] 🔒 An AI-Employee-scoped memory is invisible to other AI Employees in the same company
- [ ] Deleting a memory removes it from search **immediately**
- [ ] 🔒 A Member cannot edit or delete memory (tested)
- [ ] The 90-day cleanup job deletes old history and nothing newer

---
---

# ✅ Phase 7 Lite — Teamwork

**Agreed on:** 2026-10-11
**Time needed:** about 2 weeks (reduced from 3)
**⚠️ Build this AFTER Phase 9** — see "When to build this" below.

## What is this phase?

Until now, an AI Employee works in a **straight line**: think → tool → think → tool → finish.

Phase 7 lets it work like a **flowchart** instead:

| New ability | Simple meaning |
|---|---|
| **Branching** | "If the bug is in CSS, do this. If it is in JavaScript, do that." |
| **Parallel** | Do 3 things at the same time instead of one after another |
| **Delegating** | A manager AI Employee asks specialist AI Employees for help |

## Decisions for this phase

| # | Topic | Decision |
|---|---|---|
| 7.1 | Visual drag-and-drop builder | ❌ **No.** 1–2 weeks of work for decoration. |
| 7.2 | Multi-agent (manager → specialists) | ✅ **Yes, but minimal**: 1 manager, 2 specialists, depth 1 |
| 7.3 | Max delegation depth | **1 level.** No agent-calling-agent-calling-agent. |
| 7.4 | Replace the Phase 3 loop, or keep both? | ✅ **Replace.** Two engines means two sets of bugs. |
| 7.5 | Parallel steps | ✅ **Yes** — the main reason to adopt LangGraph |

---

## Part A — What is LangGraph? 🗺️

Right now our agent loop is a simple circle we wrote by hand. It can only go round and round.

**LangGraph lets us draw a map of steps instead.**

| Word | Simple meaning |
|---|---|
| **Node** | One box on the map. One step of work. |
| **Edge** | An arrow between boxes. "After this, go there." |
| **Graph** | The whole map |
| **State** | The information carried from box to box |

Simple example:

```
        ┌─────────────┐
        │  Read bug   │
        └──────┬──────┘
               │
        ┌──────▼──────┐
        │ What kind?  │   ← a decision box
        └──┬───────┬──┘
           │       │
     CSS   │       │  JavaScript
    ┌──────▼──┐ ┌──▼───────┐
    │ Fix CSS │ │  Fix JS  │
    └──────┬──┘ └──┬───────┘
           │       │
        ┌──▼───────▼──┐
        │  Open PR    │
        └─────────────┘
```

Our old loop could not do this. Every task followed the same path. Now the path depends on what it finds.

---

## Part B — The real reason to do this: durable checkpointing 🔖

This is the most important benefit, and it is not about features.

In **Phase 5** we built pause-and-resume by hand: when a task waits for approval, we save the AI's conversation as JSON and reload it later. It works — but it is homemade, and it only handles the simple case.

LangGraph does this properly, built in. It is called **checkpointing**:

| | Our handmade version (Phase 5) | LangGraph checkpointing |
|---|---|---|
| Pause for a human | ✅ Works | ✅ Works |
| Survive worker restart | ✅ Works | ✅ Works |
| Pause **inside a branch** | ❌ Breaks | ✅ Works |
| Pause with **parallel steps running** | ❌ Breaks | ✅ Works |
| Replay a task step by step | ❌ No | ✅ Yes |
| Battle-tested by thousands of users | ❌ No | ✅ Yes |

**So Phase 7 does not just add features — it replaces our weakest component with something proven.**

> **Interview value** 🎯 A strong, honest answer: *"I first built checkpointing by hand so I understood the problem properly, then migrated to LangGraph's checkpointer once I knew what I actually needed."* That shows judgment, not just library knowledge.

---

## Part C — Parallel steps ⚡

Some work does not need to happen in order.

**Before (one at a time):**
```
Read bug   (3s)
Search code (4s)
Read file  (2s)
Read tests (2s)
            = 11 seconds
```

**After (at the same time):**
```
Read bug ─┐
Search    ─┤
Read file ─┤  all together  = 4 seconds
Read tests┘
```

Nearly **3× faster**, and it costs the same. The AI is waiting on the network most of the time anyway.

### ⚠️ One free-tier caution

Parallel steps mean **more AI calls per minute**. On a free tier this will hit the rate limit faster.

So parallel runs have a cap: **maximum 3 at once**, and the slow-mode setting from Phase 4 still applies. Speed is nice; a blocked account is not.

---

## Part D — Multi-agent: minimal on purpose

### How it works (supervisor pattern)

```
            ┌───────────────┐
            │   Manager AI  │  "I need to fix this bug"
            └───┬───────┬───┘
                │       │
      ┌─────────▼─┐   ┌─▼──────────┐
      │ Code AI   │   │  Test AI   │
      │ writes fix│   │ writes test│
      └─────────┬─┘   └─┬──────────┘
                │       │
            ┌───▼───────▼───┐
            │   Manager AI  │  combines both, opens one PR
            └───────────────┘
```

One manager. Two specialists. **Depth 1 — specialists cannot delegate further.**

### ⚠️ Why we keep this small: errors multiply

This is the most important thing to understand in this phase.

Your single AI Employee passes **80%** of tasks (the Phase 4 gate). Now chain agents where each depends on the one before:

| Agents chained | Pass rate |
|---|---|
| 1 | **80%** |
| 2 | 0.8 × 0.8 = **64%** |
| 3 | 0.8 × 0.8 × 0.8 = **51%** |

**Three chained agents is a coin flip.**

Errors do not add up — they **multiply**. And it is worse than it looks: a mistake by agent 1 becomes agent 2's **input**, so agent 2 confidently builds on wrong information. That is much harder to spot than a crash.

**So the rules are:**

| Rule | Why |
|---|---|
| Depth limit of **1** | Stops the multiplication getting out of hand |
| Max **3** specialists per manager | Keeps it understandable |
| The manager must **check** each specialist's result before using it | Catches bad input early |
| Every delegation is written to the event log | So you can see which agent caused a failure |

> **Interview value** 🎯 Saying *"I limited delegation depth to 1 because chaining agents multiplies error rates — 80% becomes 51% at three levels"* is a much stronger answer than *"I built a multi-agent system."* It shows you understand the limits of the thing you built.

---

## Part E — What we are deliberately NOT building

Being clear about this is part of the plan, not a gap in it.

| Not building | Why |
|---|---|
| ❌ Visual drag-and-drop workflow builder | 1–2 weeks of work. Looks impressive in a screenshot, adds no real capability. Workflows are defined in config instead. |
| ❌ Deep agent nesting | The error multiplication above |
| ❌ Agents that create new agents | Unpredictable cost, very hard to debug |
| ❌ A general workflow marketplace | Far beyond scope |

---

## Part F — ⚠️ When to build this (and why not earlier)

**Build Phase 7 after Phase 9.** Two reasons:

**1. Phase 9 is what proves "production grade."** That is your actual goal.

| Phase | What it proves |
|---|---|
| **9** — security, budgets, injection defence | *"I think about production"* ← your goal |
| **7** — multi-agent, parallel | *"I can build complex features"* |

**2. Phase 7 rewrites the agent loop — the exact code that passed your 80% gate.**

Rewriting your most important working component is the single riskiest change in this whole plan. Do it when everything around it is stable, not while things are still moving.

### 🚨 The safety rule for this phase

> **After migrating to LangGraph, re-run the Phase 4 eval harness. It must still pass 8 of 10.**
>
> **If the pass rate drops, the migration is not finished.**

This is non-negotiable. A "better architecture" that performs worse is not better. The eval harness built in Phase 4 is exactly what makes this checkable instead of a matter of opinion.

---

## What we will build

| # | Thing |
|---|---|
| 1 | LangGraph set up with a **Postgres checkpointer** |
| 2 | Migrate the Phase 3 loop into a graph |
| 3 | Move Phase 5's handmade pause/resume onto LangGraph checkpointing |
| 4 | Branching nodes (decision boxes) |
| 5 | Parallel steps, capped at 3 |
| 6 | Supervisor pattern: 1 manager → up to 3 specialists, depth 1 |
| 7 | Delegation logging in the event log |
| 8 | Workflow definitions in config (no visual builder) |
| 9 | 2–3 ready-made workflow templates |
| 10 | Graph view on the run timeline — shows which box is active |
| 11 | **Re-run the eval harness** to prove nothing broke |

---

## Database work

| Table | What it holds |
|---|---|
| `workflows` | `org_id`, name, the graph definition, version |
| `graph_checkpoints` | LangGraph's saved state, so a task can resume exactly |
| `delegations` | which manager asked which specialist, and the result |

`run_events` gains new line types: `branch_taken`, `parallel_started`, `delegated_to`, `delegation_result`.

---

## Backend doors

| Door | What it does |
|---|---|
| `GET /workflows` | List ours |
| `POST /workflows` | Create one from config |
| `GET /workflows/{id}` | Read one |
| `POST /workflows/{id}/run` | Run it |
| `GET /workflow-templates` | The ready-made ones |
| `GET /runs/{id}/graph` | The run's shape, and which box is active now |

---

## Frontend screens

1. **Graph view** added to the run timeline — a simple diagram with the current box highlighted. Not editable, just a view.
2. **Parallel steps** shown side by side in the timeline, not stacked
3. **Delegation shown as a tree** — *"Manager asked Code AI → result"*
4. **Workflow template picker** when creating a task

> No visual editor. Viewing the graph is genuinely useful for debugging; editing it by dragging boxes is not worth two weeks.

---

## New words

| Word | Simple meaning |
|---|---|
| **Node** | One box on the map — one step of work |
| **Edge** | An arrow between boxes |
| **Graph** | The whole map of steps |
| **State** | The information carried from box to box |
| **Checkpoint** | A saved snapshot, so a task can resume exactly where it stopped |
| **Branch** | A fork in the path, chosen by a condition |
| **Parallel** | Several steps running at the same time |
| **Supervisor pattern** | One manager AI directing specialist AIs |
| **Delegation** | One AI Employee asking another for help |
| **Depth** | How many levels of delegation deep we are |

---

## What this phase needs

| Needs | Why |
|---|---|
| Phase 4 | The eval harness — we cannot safely migrate without it |
| Phase 5 | The approval system that checkpointing will carry |
| Phase 6 | Memory shared across graph steps |
| **Phase 9** (recommended first) | So we are not rewriting the engine while other things are still moving |

---

## ✅ Finish checklist — Phase 7 is done when:

**The migration did not break anything — check this first:**
- [ ] 🚨 **The Phase 4 eval harness still passes 8 of 10, three runs in a row.** *If not, the migration is unfinished.*
- [ ] Every Phase 4 and Phase 5 test still passes
- [ ] The Phase 3 hand-written loop is fully **removed**, not left alongside

**New abilities:**
- [ ] A workflow with a branch takes the correct path for two different inputs
- [ ] 3 parallel steps genuinely run at the same time, and are measurably faster
- [ ] Parallel steps are capped at 3, and the free-tier slow mode still applies
- [ ] A manager AI delegates to 2 specialists and correctly combines their results
- [ ] 🛑 A specialist **cannot** delegate further — depth limit enforced and tested
- [ ] Every delegation appears in the event log, so a failure can be traced to one agent

**Checkpointing (the important part):**
- [ ] ⏸ A task pauses for approval **inside a branch**, survives a full worker restart, and resumes correctly
- [ ] ⏸ A task pauses while parallel steps are running, and resumes correctly
- [ ] A completed run can be replayed step by step
- [ ] Phase 5's handmade JSON pause/resume code is **removed**

**Screens:**
- [ ] The graph view shows the active box live while a task runs
- [ ] Parallel steps appear side by side
- [ ] Delegation is shown as a readable tree

---
---

# 📍 Phases 8–10 — the roadmap (not built)

These are **not built.** They are your answer to *"what would you do next, and why in that order?"*

Each one will get its own full discussion and be written up here **only if we decide to build it.** For the interview, Phases 0–4 are the deliverable and this list is the roadmap.

---
---

---
---

# 🔨 Build log: what changed during implementation

Written after building phases 0 to 7. Every item here is a place the
plan met reality and reality won. Kept because "what I planned" and
"what I shipped" differing is normal, and the differences are the
interesting part.

## Decisions that changed

| Planned | Built | Why |
|---|---|---|
| Postgres on 5432, Redis on 6379 | **5433 and 6380** | This machine already runs PostgreSQL 18 and a Redis. They won the port binding over Docker's forward, so every connection silently reached the local database and failed authentication as user `app`. |
| Approvals in phase 7 | **Moved into phase 5** | Phase 5 adds tools that send email. Shipping those before the gate that controls them was the exact risk the plan set out to avoid. |
| Phase 7 migrates the loop to LangGraph | **Not done; capabilities built directly** | Measured rather than assumed: 25 transitive packages, including a second HTTP client and a telemetry SDK, to replace a working loop with 102 tests behind it. Its real benefit here is durable checkpointing for pausing inside a branch, and the single-path pause already works. Put to the user rather than decided silently. |
| Local embeddings via sentence-transformers | **fastembed, with a hashed fallback** | sentence-transformers pulls in torch. fastembed is ONNX-based and far lighter. When it is absent the fallback is deterministic but **not semantic**, and says so loudly in the logs rather than quietly degrading search. |

## Bugs that only running it would find

Each of these passed review and failed on contact with reality.

| Bug | Why it mattered |
|---|---|
| **Enum columns returned plain strings.** `Mapped[PolicySetting]` typed as `String(20)` hands back `str`. Equality kept working because StrEnum subclasses str, so it hid for five phases. | It surfaced as `if approval.status is not ApprovalStatus.PENDING` — an identity check that is always true, so no approval could ever be decided. `.value` raises loudly; `is` just misbehaves silently for ever. Fixed with a `StrEnumType` decorator on every enum column. |
| **The worker could not start.** arq refuses to boot with zero registered jobs. | The container exited 1 on every boot. A worker that cannot start is not a walking skeleton. |
| **The worker was reported unhealthy while working perfectly.** It inherited the image's `curl /healthz` probe. | The worker serves no HTTP — that is the point of splitting it from the API. A permanently red status means you cannot tell a working worker from a broken one. |
| **`migrate` ran baked-in image code** while api and worker used a live mount. | A new migration was invisible to it, and the error read "Can't locate revision 0002" — pointing at the migration history rather than the stale image. |
| **A module and a function shared the name `run_task`.** | The re-export shadowed the module, so importing it returned the function. |
| **Module-level async singletons broke under pytest.** Both the database engine and the Redis pool. | Each test gets a fresh event loop, so connections pooled on the previous one fail with "Event loop is closed". Correct in production, wrong in tests. Hit twice before the pattern was recognised. |
| **`TRUNCATE ... CASCADE` in a test fixture wiped seeded platform templates.** | CASCADE empties every referencing table outright, including rows with `org_id` NULL. Switched to DELETE, which follows the foreign keys instead. |
| **Autogenerate wrote app types into migrations.** | `app.db.models.base.StrEnumType(...)` makes a migration depend on application code. Rename that class later and every old migration breaks, so the history stops replaying. |
| **The default embedding model is 384-wide and no 384 vector table existed.** | The default configuration could not store a single vector. |
| **Resume created a new `Run` row**, orphaning the checkpoint, and did not execute the approved call. | The run paused for ever: the model simply asked again. The event sequence also restarted at 1 and collided with pre-pause events. |

## What is still outstanding

| Item | Status |
|---|---|
| LangGraph migration | Decision pending with the user |
| Phases 8, 9, 10 | Outlined in this document, not built |
| GitHub tool pack | The phase 4 plan named it; web, email, SQL, memory and delegation packs were built instead |
| Frontend | Not started — the brief was backend first |
| A real provider key | Everything is tested against stubs and a scripted provider. The wire format of the Gemini and OpenAI adapters has not been exercised against a live API. |

That last row is the honest gap. The adapters are written to the
documented wire formats and the agent loop around them is well tested,
but "it works against the real API" is a claim that has not been
earned yet.
