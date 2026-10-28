# Custom agents, created in chat

Status: **built.** This page describes how agents work today, the rules they keep, and what is not built.

## What an agent is

An **agent** is a saved, named helper that a person designs: its instructions, which tools it may use, which AI it prefers, and optionally a schedule. A person can have up to 30.

A chat has a fixed *mode* (General, Study, Work, Research, Code) and an optional *team* switch that brings in six built-in helpers (researcher, analyst, writer, critic, developer, generalist). Those live in code. Agents are the part a person controls.

### Decisions

| Question | Decision | Why |
|---|---|---|
| Private memory per agent? | No. One shared memory per person | Keeps one memory the person can read and edit, instead of a separate memory per helper |
| Does an agent get its own runtime? | No. A run is an ordinary assistant run with the agent's instructions | Permissions, approvals, memory and cost tracking apply unchanged |
| How is an agent made? | By chatting, then pressing Create on a draft card | Nothing exists until a person presses the button |

## How it works

**Creating one.** The person says in Chat: "I want an agent that reads my newsletters and writes a Friday digest". The assistant asks what it needs, then calls the `propose_agent` tool. That tool changes nothing. It shows a **draft card** with a name, a description, the tools, the preferred AI, an optional schedule, and a **readiness check**: is each app connected, allowed by the platform, granted by the person, and permitted on the Permissions page? **Create** stays off until every check passes. Pressing it saves the agent.

**Scheduling.** An agent can run daily, on weekdays, or on chosen days, at a time in the person's time zone. A worker job looks for due agents every minute. Before each run it checks the same links again. If one is broken, the agent is marked as needing attention and the person is told, instead of failing at night. An agent that writes to a spreadsheet may only write to the sheet the person named.

**Running.** An agent can be run now, paused, resumed, edited or removed. Removing archives it, so old chats that used it still read. Each agent's runs are written into a conversation of its own, so the results read like any chat. The person can also open a chat with the agent.

**Starters.** The five chat modes and the six helper roles are shown as read-only starters that a person can copy into an agent and edit.

## The AI Agents page

It manages agents. It does not create them; Chat does. It has four tabs, and the tab is part of the address (`/agents?tab=tree`):

1. **Agents.** The list, with schedule, last run, cost, and run now, pause, edit.
2. **Tree.** A live tree of the person, the assistant and the agents, with each agent's tools hanging off it. It is built from real runs, and the scheduler flow shows what runs next. Branches in use light up.
3. **History.** Past runs with filters, a detail view of each run, and replay of its steps from the event log.
4. **Models and cost.** What the models cost, an estimate of what was saved against a reference model, and free versus paid keys. Every figure is an estimate, because Baton cannot see the provider's invoice.

## Rules it keeps

1. **An agent can only narrow, never widen.** Its tool list is intersected with the person's Permissions. An agent cannot reach a tool the person has blocked.
2. **Agents cannot create agents.** `propose_agent` is given only to a chat that is designing an agent, never to a saved agent or a scheduled run. Otherwise one poisoned web page could make an agent spawn a swarm.
3. **Depth stays 1.** A team helper cannot call another helper.
4. **"Ask me first" becomes a refusal for a team helper**, because a helper works inside the lead's step and cannot pause for a person. A scheduled agent run pauses for approval like any run.
5. **Caps.** At most 30 agents per person, a step limit per run (default 40, at most 80), and at most six helper calls per chat message.
6. **Isolation.** Agents are scoped by `owner_id`. Another person's agent is a 404, and the isolation test covers the table.

## Data and API

Table `agents`: `owner_id`, `name`, `handle` (unique per person), `description`, `instructions` (at most 8,000 characters), `model` (`auto` or `provider:model`), `routing`, `tools` (a list of tool names, or null for everything the person allows), `archived`, and the schedule fields. Agents are not versioned.

Also: `conversations.agent_id` (nullable) and `tasks.agent_id` (nullable), so a run and its chat know which agent produced them.

Routes (all under `/me/agents`): `GET /overview`, `GET /tree`, `POST /readiness`, `POST /` (create), `GET/PATCH/DELETE /{id}`, `GET /{id}/readiness`, `POST /{id}/pause`, `/resume`, `/run` and `/chat`. History is under `/me/history` and cost under `/me/usage`. See the [LLD](LLD.md) for the full list.

## Tests

- Narrowing: an agent listing a blocked tool never gets it.
- No recursion: a team helper is never offered `propose_agent`.
- Readiness: each failed link reports a plain sentence and a fix.
- Schedules: due agents start once, and a broken link stops the run with a note.
- Cross-person isolation on every route.
- An archived agent is not callable, and a conversation that used it still reads.

## Not built

- Using an agent as a team helper, and `@mention` of an agent.
- Effort-based model choice.
- Retry that escalates to a stronger model after a failed agent run.
- Sharing an agent as a file.
