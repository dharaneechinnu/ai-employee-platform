# Baton

**Pass every task to the right AI.**

Bring free AI keys (Gemini, Groq, OpenRouter, Mistral and more). For every prompt, Baton picks the connected model that is best at that kind of task, and hands the work to the next one if a model hits its limit, the way a relay runner passes the baton.

[![Watch the Baton launch ad (48 seconds, with sound)](docs/screenshots/00-baton-ad.jpg)](docs/routing-ad.mp4)

▶️ **[Watch the 48-second launch ad](docs/routing-ad.mp4)**: free keys, the right model for each prompt, and the hand-off when one hits its limit.

Baton is a **personal AI assistant** that does real work. One person signs in and gets:

- a chat assistant that can use real tools, not just talk;
- their own AI keys from any provider (you bring your own key, so you pay the provider directly);
- their own connected apps: Google, Microsoft, GitHub, a mailbox and a database;
- one memory that the assistant and every agent share;
- **agents** they design by chatting, which can run on a schedule;
- approvals, so nothing risky happens until they say yes.

"Baton" is the product name. The repository keeps its original name, `ai-employee-platform`, from when the product was called "AI Employees" and was a tool for companies to "hire" AI workers. It is now a personal assistant: every account belongs to one person, and that person's data is kept apart from everyone else's.

![The product overview page](docs/screenshots/01-landing.png)

> **Status:** the backend, worker and React frontend are built and run with one command. Chat is the home screen. Agents can be designed in chat and run on a schedule. Anyone can create an account at `/register` and sign in with their email or username; a Platform Admin can also create an account and send a one-time setup link.
>
> 🎬 **Videos:** the Baton launch ad, plus a narrated ad, a live demo and an animated overview, are [at the bottom of this page](#-product-videos). All but the launch ad were recorded from the earlier company version, so some screens look different now.

## What problem this solves

Most AI chat tools stop at advice. They:

- forget everything when the chat closes;
- cannot reach your real apps;
- cannot be trusted with actions that have consequences.

This assistant fixes all three. It remembers what you tell it, uses your connected apps with your permission, and pauses for your approval before it changes anything.

## How it works

```
You            →  create an account at /register (or open a setup link from an admin)
You            →  add one or more AI keys; free tiers like Gemini and Groq are enough
You, in Chat   →  "Find last week's invoices in Gmail and list them in a sheet."
Baton          →  picks the connected model that suits the task, passes it on if one is busy
The assistant  →  plans, uses tools, streams every step live, logs everything
Anything risky →  pauses and asks you (in the app, by email or in Slack)
Result         →  the work done, with a full record of each step and its cost
```

## The screens

The menu on the left (you can drag it to the bottom or the right) has:

| Screen | What it is for |
|---|---|
| **Chat** | The home screen. Talk to the assistant, pick a mode and an AI, and design new agents. |
| **AI Agents** | Manage the agents you made: edit, schedule, run now, pause, see their tree and cost. |
| **Approvals** | Actions waiting for your yes or no. |
| **Memory** | What the assistant remembers about you and your work. |
| **Connections** | Your apps: Google, Microsoft, GitHub, a mailbox and a database. |
| **AI Providers** | Your AI keys and the models each one can use. |
| **Permissions** | Always allow, Ask me first or Blocked, for every tool. |
| **Notifications** | Where you hear about approvals, finished work and failures. |

The Platform Admin has a separate area at `/platform`. See [Who can do what](#who-can-do-what).

## Agentic AI features

What makes this an *agent* rather than a chatbot, in plain words.

### 1. It works in a loop: think, use a tool, check, repeat

The assistant plans a step, calls a tool, reads the result, and decides what to do next, until the job is done. If a tool fails, the error comes back as a sentence ("that file does not exist"), so the assistant can correct itself instead of crashing. Every step is streamed live and kept for replay.

![A run streaming its steps live](docs/screenshots/04-live-run.png)

### 2. It uses real tools

| Pack | What the assistant can do |
|---|---|
| **Google Workspace** | Search, read, draft and send Gmail, replying in the same thread; archive, label and mark emails; list, create, move and cancel Calendar events (past ones too); search and read Drive files, PDFs included; create, read and write Google Sheets |
| **Microsoft 365** | The same for Outlook mail (archive, flag, categories), Outlook calendar and OneDrive; read, add rows to and update **Excel** workbooks in OneDrive |
| **Slack and Teams** | Post a summary or an alert to one channel, through the incoming webhook you paste in (asks you first) |
| **Any mailbox (IMAP)** | List, read, draft and send email with an app password |
| **GitHub** | Read code, issues, pull requests and CI; comment, open issues, propose changes as pull requests. See feature 14 |
| **Database** | List tables, describe them, and run **read-only** SQL |
| **Web** | Read a public web page or PDF; search the web (when the server has a search key set). Every redirect is checked, so a page cannot send the request into the private network |
| **Memory** | Remember facts and recall them later |
| **Everyday helpers** | Calculator, current time, text tools, assemble a report, run a short Python program (asks you first) |

### 3. One-click connections, and secrets never reach the AI

Connect Google or Microsoft with one sign-in. When you connect, you choose which parts the assistant may use (for example Gmail and Sheets, but not Drive) and whether it may only read or also edit. Tokens are encrypted with a key tied to your account and refreshed automatically. The AI never sees them: the worker adds the credential only at the moment a tool runs. That is why a prompt-injection attack cannot steal a key: the key was never in the conversation.

![Connections: Google connected in one click](docs/screenshots/02-connections.png)

### 4. Always allow, Ask me first, or Blocked: for every tool

Every tool gets one of three settings. You choose it on each connected app (Connections) and on the **Permissions** page.

- **Always allow**: it runs straight away, with **no approval**.
- **Ask me first**: the run pauses until you approve.
- **Blocked**: it never runs.

By default, reading is always allowed and sending asks first. Switching something that cannot be undone (like sending an email) to Always allow asks you once more, in plain words. Agents and team helpers follow the same rules. A tiny list of catastrophic actions (deleting a repository, force-pushing, emailing all contacts) can never be allowed.

A tool runs only when every layer says yes: the platform allows that part of the app, your connection was granted that permission, the agent lists the tool, and your Permissions page allows it.

![Each connected app lists its tools with a switch](docs/screenshots/19-tool-permissions.png)

![Always allow on a send asks once more](docs/screenshots/20-always-allow-confirm.png)

![The Permissions page](docs/screenshots/10-permissions.png)

![Tool picker: Gmail tools ticked, sending asks first](docs/screenshots/03-tool-picker.png)

### 5. You approve risky actions, and the run waits

When an action needs approval, the run **pauses** and its conversation so far is saved to the database. The worker moves on to other jobs. When you approve, the run **resumes exactly where it stopped**; a rejection ends it cleanly. Requests expire after 24 hours, so nothing waits for ever. The approval card shows the real action (the full email, say), not a summary.

![Approvals: the full email is shown before anyone agrees](docs/screenshots/06-approvals.png)

### 6. Approve from your inbox or Slack

You can get an email with your own **Approve / Reject** link, and a Slack channel can get the same message. Opening a link only *shows* the action; nothing is decided until a person presses a button, so a mail scanner that opens links cannot approve anything. Slack links ask whoever clicks to sign in.

![Approve from an email link](docs/screenshots/07-approve-from-email.png)

### 7. Agents you design by chatting

An **agent** is a saved helper with a name, instructions, the tools it may use and the AI it prefers. To make one, say in Chat "I want an agent that ...". The assistant asks what it needs, then shows a **draft card** with a readiness check: is each app connected, allowed by the platform, granted by you, and permitted on your Permissions page? **Create** stays off until every check passes. Nothing is saved until you press it, and agents cannot create other agents.

An agent can **run on a schedule** (daily, on weekdays, or on chosen days, at a time in your time zone). Before each run, the worker checks the links again and tells you if something broke, instead of failing all night. Each agent's runs are written into a conversation of its own, so you read the results like any chat. The **AI Agents** page is where you schedule, run now, pause, edit, and see each agent's tree and cost. You can have up to 30 agents.

![Creating an agent with plain questions](docs/screenshots/12-new-employee.png)

![The agent tree](docs/screenshots/05-agent-tree.png)

### 8. It does independent steps at the same time

When the model asks for several independent tool calls, up to three run in parallel ("Running in parallel · 2 at once" in the log), so a run finishes sooner.

![The log shows two steps running at once](docs/screenshots/14-parallel-steps.png)

### 9. It remembers you

The assistant can **remember** facts and **recall** them later. Search works **by meaning** (vector embeddings in pgvector) **and by exact words** (full-text search), combined. There is one memory per person, shared by the assistant and all your agents. You can read and delete anything on the **Memory** page.

![Memory](docs/screenshots/09-memory.png)

### 10. Seatbelts: budgets and cancel

Every run has caps on steps, tokens and time, so a confused agent cannot loop all night. Any run can be cancelled; the **Cancel** button stays on screen while a run is working. The backend also supports a dry-run flag on a task (plan the work, send and change nothing); Chat does not offer it yet.

![Dry run switched on before assigning a task](docs/screenshots/15-dry-run.png)

### 11. Every step is on record

Each event (thinking, model call, tool call, result, approval) goes into an append-only log. That one log powers live streaming, reconnecting without losing steps, replay, the agent tree and the record of what happened. Steps, tokens and an estimated cost are shown for every run.

![A finished run with its result and cost](docs/screenshots/08-result.png)

### 12. Any AI provider, with your own key

**AI Providers** lists the providers the Platform Admin has turned on: for example Claude (Anthropic), OpenAI (ChatGPT), Gemini, Groq, DeepSeek, Mistral, OpenRouter, Together, NVIDIA and Sarvam. You add your own key for each one you want, so the bill stays with you. **Your own server** connects any open-source model (Llama, Qwen, DeepSeek, Mistral, Gemma) running on vLLM, Ollama, LM Studio or LiteLLM: paste the address of its OpenAI-compatible API and the model name. **Load models** asks the provider which models your key can use. Claude uses its own adapter, so its thinking blocks are passed back unchanged between tool calls, as the API requires.

![Bring your own AI key](docs/screenshots/13-own-ai-key.png)

![Your own model server, connected, with the model picker open](docs/screenshots/22-own-model-server.png)

### 13. Chat modes, and switching AI mid-conversation

A **mode** tells the assistant who you are, so you do not re-explain yourself every message:

| Mode | For | How it answers |
|---|---|---|
| **General** | Everyone | Clear and direct |
| **Study** | Students | Explains step by step with an example, checks understanding, gives hints before full homework answers |
| **Work** | Professionals | Concise and ready to use: drafts, decisions, next steps |
| **Research** | Researchers | Summary, findings, open questions; separates fact from inference; never invents citations |
| **Code** | Developers | A careful pair programmer: reads before it suggests, keeps changes small, flags edge cases and tests |

Pick the **AI** under the message box and switch it at any time: history is plain text, so a conversation started on Gemini carries on with Claude or your own Llama, and every reply says which model wrote it. There is no tool list to manage in Chat: every built-in tool is on, and an app's tools switch on once you connect that app. Your Permissions still decide each call. Each answer shows what it used.

![Study mode: a step-by-step answer with code and a table](docs/screenshots/23-chat-study.png)

![Approving an action inside the chat](docs/screenshots/26-chat-approval.png)

![Code mode for developers](docs/screenshots/30-code-mode.png)

### 14. For developers: GitHub tools

Connect **GitHub** with a fine-grained personal access token, limited to the repositories you choose, and the assistant and your agents get 11 developer tools:

| Reads (run on their own) | Changes (ask you first) |
|---|---|
| See repositories · Search code · Read a file or folder · See issues and pull requests · Read an issue or PR with its comments · **Review a PR's diff** · See recent commits · **Check CI**: which job and step failed | Comment on an issue or PR · Open an issue · **Propose a code change**: new branch, files written, pull request opened |

The rule is simple: **the default branch is never written.** A change always arrives as a pull request for a person to review and merge. There is no merge tool, and deleting a repository or force-pushing are blocked platform-wide.

![The GitHub connection and its tools, each with its permission](docs/screenshots/29-github-tools.png)

### 15. Team mode: a lead and helpers

Switch on **Team** in a chat and the assistant becomes a lead with helpers: a **researcher**, an **analyst**, a **writer**, a **critic**, a **developer** and a **generalist**. For a big question the lead hands independent parts to several helpers in the same step, so they **work at the same time**, then checks and combines their answers. You can watch each helper start and finish live.

The limits are deliberate: helpers cannot start their own chains, can only **read**, follow your Permissions, see only the task they were given, and get a small step budget. There are at most six helper calls per message, and their cost is counted in the message's cost. A helper that could not finish is tried once more on your strongest AI. Team mode is for chats; scheduled agent runs work alone.

*Planned, behind a setting that is off by default (`AGENT_SUPERVISOR`):* a supervisor that first picks which helpers a request needs, and a writer-and-critic review loop for reports (at most two rounds).

![The team working in parallel](docs/screenshots/24-chat-team-working.png)

![The combined answer, with the team that produced it](docs/screenshots/25-chat-team-answer.png)

### 16. Connect several AIs; each task goes to the one that suits it

With the AI set to **Automatic**, every task (a chat message, an agent run, each team helper) goes to the connected AI that fits it best:

1. **What kind of task is it?** Fast rules decide most cases for free: code or an error message is coding, a long paste is a long document, "draft an email" is writing. Only when the rules cannot tell is your cheapest AI asked, in one tiny call.
2. **Which AI is best at it?** Each model has a small profile (skill per kind of task, speed, cost). Your preference decides the trade-off: **Balanced** (the default), **Best quality**, **Lowest cost**, or **Private only** (your own server, so nothing leaves it).
3. **If it's busy, the next one takes over.** Your other connected AIs are kept as fallbacks, so a rate limit or an outage at one vendor does not fail the run.

Every answer says which AI wrote it and why. You can still pin one AI in a chat or an agent.

![Automatic chose Claude for a coding question; when it was unavailable, the user's own server took over](docs/screenshots/27-automatic-routing.png)

![What Automatic sends to each connected AI](docs/screenshots/28-providers-strengths.png)

### 17. You hear about it where you work

Email or Slack messages when an approval is needed, when work fails, or when it finishes. Each can be turned on or off on the **Notifications** page.

![Notification settings: email and Slack](docs/screenshots/11-notifications.png)

### 18. Speak instead of typing

Press the mic, say what you need, press it again: the words appear in the message box, ready to check before you send. It uses **Whisper Large v3 Turbo** (open source, very good with Indian accents) through **your own Groq key**. Without a Groq key you get the browser's built-in voice typing instead. Recordings are never stored, and approvals stay button-only on purpose: voice can ask, but never approve.

![Voice typing: the mic is listening](docs/screenshots/16-voice-input.png)

### 19. A welcome tour, and tips when you need them

New people get a short animated welcome, then a spotlight tour of each screen the first time they open it. Tips for a feature appear the first time it shows up. Phones skip what is tucked in the menu. The **?** button replays any tour, and tips can be turned off.

![The welcome intro](docs/screenshots/17-welcome.png)

![A coachmark spotlighting the task box](docs/screenshots/18-coachmarks.png)

## Who can do what

There are two kinds of account, and they are kept fully apart.

| | **You** (a normal account) | **Platform Admin** |
|---|---|---|
| Signs in at | `/login` | `/platform`, with a different kind of token |
| Uses Chat, agents, memory, connections, keys, permissions, approvals | ✅ your own only | ❌ |
| Creates an account | ✅ your own, at `/register` | ✅ for anyone, with a setup link |
| Suspends or restores an account | ❌ | ✅ (nothing is read or deleted) |
| Sets up the shared Google and Microsoft sign-in apps | ❌ (you may add your own app instead) | ✅ |
| Opens or closes parts of an app (for example Sheets edit) for everyone or one account | ❌ | ✅ |
| Manages the AI provider catalog | ❌ | ✅ |
| Reads anyone's chats, memory, tasks, keys or tokens | — | ❌ **never**: no endpoint returns them |

What the Platform Admin can see about an account: email, name, active or not, when it was made, how many tasks it has run, and which AI providers it has connected (yes or no, never the key). Every Platform Admin action is written to an audit log that the application cannot edit or delete.

## Stack

| Layer | Technology |
|---|---|
| Frontend | React · TypeScript · Tailwind CSS · Vite |
| Backend | Python · FastAPI · SQLAlchemy 2.0 (async) |
| Agent runtime | A hand-written agent loop, run inside a LangGraph graph |
| Database | PostgreSQL + pgvector |
| Queue | Redis + arq workers |
| AI | Claude · OpenAI · Gemini · Groq · DeepSeek · Mistral · OpenRouter · Sarvam · any OpenAI-compatible server (you bring your own key) |
| Tools | Built-in packs (Google, Microsoft, GitHub, mailbox, database, web, memory, helpers) |
| Deployment | Docker Compose |

## Key design decisions

| Decision | Why |
|---|---|
| **Every table that holds a person's data has `owner_id`** | Filtering happens in one repository layer, and a test fails if a new table leaves the column out. One person can never read another's data by a forgotten filter. |
| **You bring your own AI key** | You pay your provider directly; nobody can run up another person's bill. |
| **Tools declare a side-effect label** (read / write / destructive) | Permissions and approvals can be enforced, not just suggested. |
| **Append-only event log per run** | Live streaming, reconnect-safe, replayable, auditable, all from one property. |
| **Credentials never enter the model context** | Prompt injection cannot leak a key that was never there. |
| **Helpers are one level deep; agents cannot create agents** | Errors multiply with every hop; a bounded tree stays debuggable and cannot spawn a swarm. |
| **The Platform Admin cannot read anyone's content or keys** | The endpoint does not exist, so it cannot be misused. |

## Documentation

| Document | What it covers |
|---|---|
| 🏗️ **[High Level Design](docs/HLD.md)** | Who uses it, the five running parts, the data model, the main flows, security and scale. |
| 🔧 **[Low Level Design](docs/LLD.md)** | Folder layout, tables, the API, the agent loop, tools, permissions, events, encryption, tests. |
| 🤖 **[Agents plan](docs/AGENTS_PLAN.md)** | How agents are designed in chat, scheduled and limited. |
| 🔑 **[Google connection](docs/GOOGLE_CONNECTION.md)** | What happens when you connect Google, and what can go wrong. |
| 📋 **[Implementation Plan](docs/IMPLEMENTATION_PLAN.md)** | The original phase-by-phase build plan, with notes on what changed. |

## Roadmap

| Step | What | Status |
|---|---|---|
| 0–7 | Foundation, sign-in, AI providers and tools, background runs with live streaming, permissions and approvals, memory, parallel steps and a team of helpers | ✅ Built |
| + | One-click Google / Microsoft, notifications, approve from email or Slack, GitHub | ✅ Built |
| + | Personal accounts: one person per account, created by a Platform Admin with a setup link | ✅ Built |
| + | Self sign-up with usernames; sign in with email or username | ✅ Built |
| + | Renamed to Baton; sign-in and launch ad lead with free keys and per-task routing | ✅ Built |
| + | Agents designed in chat, schedules, readiness checks, per-service read/edit permissions | ✅ Built |
| + | The run inside a LangGraph graph | ✅ Built |
| Trial | LangGraph-saved approval pauses (`AGENT_CHECKPOINTER`) and a team supervisor graph (`AGENT_SUPERVISOR`) | 🧪 Built, off by default |
| + | Excel in OneDrive, Slack and Teams posting, PDF reading, moving and cancelling events, threaded replies and inbox tidying | ✅ Built |
| Planned | Effort-based model choice | 🗒️ Not built |
| 8–10 | Reliability · security and cost · production readiness | 🗒️ Outlined, not built |

## Running it

```bash
docker compose up --build        # all five services
make test                        # the test suite, on a separate test database
make lint                        # ruff + mypy strict
```

Host ports are **5433** (Postgres) and **6380** (Redis), not the defaults, so
the containers do not clash with a database already installed on your machine.

### Your first account

The quickest way: open <http://localhost:5173/register>, pick a username, enter your email and a password, and you land in **Chat**. Add a key under **AI Providers** to start; a free Gemini or Groq key is enough.

To create an account for someone else, use a Platform Admin:

1. Create a Platform Admin:

   ```bash
   cd backend && python -m scripts.bootstrap_admin --email admin@example.com
   ```

   It prints the password once if you did not give one.
2. Open <http://localhost:5173/platform> and sign in as that admin.
3. On **People**, enter the person's email (and name, if you like) and press **Create and get setup link**. The link is shown once.
4. Open the link (it looks like `http://localhost:5173/login?token=...`). Choose a password. The link works once and expires after 72 hours.
5. You land in **Chat**. Add a key under **AI Providers** to start.

One-click connections and email notifications need a few settings (OAuth
client ids, SMTP); they are listed with comments in `.env.example`. See
[DEMO.md](DEMO.md) for a short tour.

### Screenshots and videos

The images and videos in this README were made from the earlier company version, using a mock demo server in `frontend/scripts/demo/`. That mock server has not been updated for personal accounts yet, so these commands need it updated before they produce current screens:

```bash
cd frontend && npm run build
node scripts/readme-screenshots.mjs   # docs/screenshots/*.png
npm run demo:record                   # docs/product-demo.mp4
npm run ad:voice-setup && npm run ad  # docs/product-ad.mp4 (narrated)
```

## What is checked

| Check | How |
|---|---|
| Tests | `make test`: unit, per-person isolation, and integration tests against real Postgres |
| Types | mypy **strict** |
| Lint | ruff with bugbear, bandit, async and blind-except rules |
| Migrations | 24 (0001 to 0024), applied with `make migrate` |
| Frontend | TypeScript strict build; screens checked in dark, light and phone widths |
| UX audit | The `icp-ux-audit` skill (`.claude/skills/`) reviews screens on desktop and phone |

---

## 🎬 Product videos

▶️ **Watch on Google Drive:** [Product videos, earlier version](https://drive.google.com/file/d/1L8DQJJeDJeSN5XoC2bQ4jBIS5LagYWRL/view?usp=sharing)

The same files are in this repository under `docs/`. The first one shows the product as it is now; the others show the earlier company version.

To rebuild the new one: `node scripts/ad-routing/render.mjs out.mp4` (in `frontend/`), then `AD_SCRIPT=scripts/ad-routing/script.json python3 scripts/ad/make_ad.py out.mp4 docs/routing-ad.mp4`.

| Video | What it shows |
|---|---|
| 🆕 **[Baton launch ad](docs/routing-ad.mp4)** (0:48) | The current product: free AI keys, each prompt sent to the model that suits it, automatic fallback when one hits a limit, and scheduled agents. Zoom punches, shakes and a different transition at every cut, an open-source Kokoro voice and subtitles |
| 🎬 **[Narrated ad](docs/product-ad.mp4)** (1:08) | Six features with title cards, zooms and spotlights, a voiceover in sync with subtitles, and music |
| 🖥️ **[Live demo](docs/product-demo.mp4)** (0:58) | The app recorded in use, start to finish |
| ✨ **[Animated overview](docs/product-film.mp4)** (1:05) | An illustrated tour of the features |
| 🧭 **[Welcome and tips](docs/coachmarks-demo.mp4)** (0:48) | The first-sign-in welcome, then the spotlight tour |
