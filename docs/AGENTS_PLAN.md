# Custom agents, created in chat

> **Update, October 2026.** The Build tab is gone: agents are made in Chat. Say
> "I want an agent that ..." and the assistant asks what it needs, then shows a
> draft card with a readiness check (is each app connected, allowed by the
> platform, granted by you, permitted on your Permissions page). Create stays
> off until every link passes. Agents can run on a schedule you choose, in your
> time zone; a worker job starts them, re-checks the links first, and tells you
> when something broke. The AI Agents page only manages them: schedule, run now,
> pause, edit, tree, cost. Permissions are split by service (Gmail, Drive, Sheets,
> Calendar) and level (read, edit) at the platform (for everyone or for one
> person), connection and agent levels. Not built yet: effort-based model choice, failure-based retry and
> escalation, usage and quality monitoring, and Excel through Microsoft 365.


Status: **planned, not built.** Decisions are settled; the phases below are the order to build in.

## What we are building

An **agent** is a saved, named helper that a person designs: its instructions,
which tools it may use, and which AI it prefers. A person can have many.

Today a chat has one fixed *mode* (General, Study, Work, Research, Code) and an
optional *team* switch that brings in four hard-coded specialists (researcher,
analyst, writer, critic). All of it lives in code, so nobody can change or add
any of it. Agents replace that with one idea:

- the five modes and four specialists become **starter agents** that ship with
  the product and can be copied and edited;
- a person's own agents sit beside them;
- an agent can be **the chat's persona** or **a teammate** the assistant calls.

### Decisions already made

| Question | Decision | Why |
|---|---|---|
| What does "multiple agents" mean? | Both: persona *and* teammates | Persona alone is custom GPTs; teammates is what makes it an agent system |
| Private memory per agent? | No. One shared memory per person | Keeps one memory the person can read and edit, instead of a separate memory per helper |

## How it works

**Creating one.** The person says, in plain words, "make me an agent that reads
my newsletters and writes a Friday digest". The assistant calls a
`create_agent` tool with a name, instructions and tool list. That tool is a
*write*, so under the default permissions it **pauses for approval**, and the
approval card shows every field. No new confirm UI: the existing approval flow
*is* the confirmation. Approve and the agent exists; reject and nothing happens.

**Using one as the persona.** Pick an agent when starting a chat, or switch
mid-chat. Its instructions replace the mode's.

**Using one as a teammate.** In team mode the assistant can call any of the
person's agents (and the starters) in parallel, and combine what comes back.
`@mention` addresses one directly for a single turn: "@Digest summarise this".

## The AI Agents tab (added after the first draft)

Agents get their own tab in the menu, separate from Chat. It has three parts:

1. **Builder chat.** A conversation whose only job is making agents. You
   describe what you want; it asks what it needs, then shows a live draft card
   (name, what it does, tools, preferred AI). Create / Edit / Discard. Nothing is
   saved until you press Create. This is the main way to make an agent.
2. **Agent tree.** Your agents drawn as a tree: you, your assistant, and the
   agents it can call, with each agent's tools hanging off it. Built from real
   runs, not a mock-up: the branches that were actually used light up.
3. **Flow and cost.** A flow view of one agent's run, drawn differently from
   the route view in Chat (that one shows *where a request went*; this one shows
   *who did what and what it cost*): a timeline lane per agent, a bar per step,
   and tokens and cost per lane and in total.

It must look and behave differently from the existing route view, not reuse it.

## Rules it must keep

1. **An agent can only narrow, never widen.** Its tool list is intersected with
   the person's Permissions. An agent cannot reach a tool the person has blocked.
2. **Agents cannot create agents.** `create_agent` is lead-only and is never
   offered to a specialist. Otherwise one poisoned web page could make an agent
   spawn a swarm.
3. **Depth stays 1.** A teammate cannot call another teammate.
4. **"Ask me first" becomes a refusal for a teammate**, as it does now: a
   specialist works inside the lead's step and cannot pause for a person.
5. **Caps.** A maximum number of agents per person, and the existing maximum of
   specialist calls per reply.
6. **Isolation.** Agents are scoped by `owner_id`; another person's agent is a
   404, and the isolation guard test covers the new table.

## Data and API

New table `agents`: `owner_id`, `name`, `handle` (unique per person, used for
`@mention`), `description`, `instructions` (max 8,000 chars), `model` (`auto` or
`provider:model`), `routing`, `tools` (list of tool names, or null for "everything
I'm allowed"), `archived`. Not versioned yet; a reply records which agent and
which instructions hash produced it, so history stays explainable.

Changes elsewhere: `conversations.agent_id` (nullable, SET NULL) for the persona;
`tasks.agent_id` (nullable) for a one-turn `@mention`, so the reply can say who
answered.

Routes: `GET/POST /me/agents`, `GET/PATCH/DELETE /me/agents/{id}`; the
conversation create/update routes accept `agent_id`.

Starter agents stay in code as read-only defaults. "Copy to mine" creates a row.
That avoids seeding rows for every person and lets starters improve in a release.

## Build order

| Phase | Delivers | Done when |
|---|---|---|
| 1 | `agents` table, CRUD, pick an agent as a chat persona; modes become starter agents | A person can write an agent by hand and chat with it |
| 2 | `create_agent` tool with the approval card | "Make me an agent that…" produces a card, and approving it creates the agent |
| 3 | Agents as teammates in team mode, and `@mention` | The assistant calls two custom agents in parallel and combines them |
| 4 | Copy a starter, export/import as JSON | A person can share an agent as a file |

Build 1 and 2, then **use it for a while before building 3**. Phase 3 is the
largest and its shape depends on what people actually create.

## Tests that must exist

- Narrowing: an agent listing a blocked tool never gets it; an agent can't use a
  tool its person hasn't connected.
- No recursion: a teammate is never offered `create_agent`.
- Creating through chat pauses for approval, shows every field, and creates
  nothing on reject.
- Handles are unique per person and a mention of someone else's agent resolves
  to nothing.
- Cross-person isolation on every route.
- An archived agent is not callable, and a conversation that used it still reads.

## Open items (decide when we reach them, not now)

- Whether an agent's instructions *replace* the mode's or *add to* it. Planned:
  replace, since a starter agent already contains the mode's text.
- Whether to let a person edit a proposed agent on the approval card before
  approving. Planned: no for phase 2; reject and ask again.
- Per-agent cost and usage display.
