---
name: icp-ux-audit
description: Audit the AI Employees web app's UI and UX through the eyes of its ideal customer (ICP) personas, then write a short plain-English report with prioritised fixes. Use when asked to audit, review or improve the UI/UX, check a screen "from the user's side", or before a release or demo.
---

# ICP UX audit

Judge every screen as the people who pay for and use this product would,
not as its developer. A screen passes when the persona can finish their
job on it without help, without fear, and without reading docs.

## 1. Who the ICP is

Small and mid-size companies (20–300 people), India-first, whose
business teams want AI help without hiring engineers. Three personas
cover almost every screen:

| Persona | Role in the app | Tech level | Device | What they fear |
|---|---|---|---|---|
| **Asha, Ops lead** (buyer, company **admin**) | Creates AI Employees, approves risky actions, reads results | Comfortable with SaaS, not a developer | Laptop at work, **phone for approvals** | "The AI emails a customer something wrong in my name." |
| **Priya, Sales / HR member** | Assigns tasks, reads results, uses Memory | Non-technical | Laptop and phone, often on the move | "I'll break something" / "I don't know what to type." |
| **Arjun, founder or IT admin** | Connects Google/Microsoft, AI keys, permissions | Technical | Laptop | Data leaks, surprise bills, no audit trail |

(The Platform Admin screen is internal; audit it last and lightly.)

## 2. The jobs to test

Walk these end to end; each one is a pass/fail story, not a page.

1. **First 10 minutes** (Arjun → Asha): sign in → add an AI key → connect Google → create an AI Employee → assign the first task. Can a new admin find the next step without guessing?
2. **Daily task** (Priya): pick an employee → describe work (typed or spoken) → watch it run → read and copy the result.
3. **Approve on the phone** (Asha): open the approval link or the Approvals page at 390 px wide → understand exactly what will happen → approve or reject.
4. **Trust check** (Arjun): who can do what, what each tool may do, what a run cost, what was done.
5. **Member view** (Priya): admin-only things are hidden, and nothing she sees is a dead end.

## 3. The rubric

Score each screen 1–5 on each line. Anything at 1–2 is a finding.

| # | Check | What "good" looks like here |
|---|---|---|
| 1 | **Clear next step** | One obvious primary action; empty states say what to do and link to it |
| 2 | **Plain language** | No internal jargon (`run`, `seq`, `side effect`, `provider`, raw model ids, raw enum values) without a plain gloss |
| 3 | **Feedback** | Every action shows progress, success and failure; errors say what to do next |
| 4 | **Trust and safety** | Risky actions say what will happen, to whom, before it happens; cost and limits are visible |
| 5 | **Consistency** | Same words, buttons and layouts for the same thing across screens |
| 6 | **Mobile** | Works at 390 px: no sideways scroll, tap targets ≥ 44 px, nothing cut off |
| 7 | **Accessibility** | Every control has a name; inputs have labels; text ≥ 12 px; focus is visible; not colour-only |
| 8 | **Visual hierarchy** | The important thing is the biggest/brightest; density suits the persona |
| 9 | **Speed to value** | Fewest steps and fields to finish the job; sensible defaults |
| 10 | **Recovery** | Undo, cancel or edit after a mistake; nothing destructive by one click |

## 4. Procedure

1. **Start the app** with seeded data (see `DEMO.md`): Postgres, Redis, API on :8000, Vite on :5173, accounts `owner@victopia.com` (admin) and `priya@victopia.com` (member).
2. **Capture** every screen at desktop (1440×900) and phone (390×844), as admin and as member, with automatic checks:
   ```bash
   cd frontend && node ../.claude/skills/icp-ux-audit/capture.mjs <out-dir>
   ```
   This writes `<out-dir>/<role>-<page>-<device>.png` and `<out-dir>/checks.json`
   (sideways overflow, small tap targets, unnamed controls, unlabeled
   inputs, tiny text, console errors per screen).
   For populated states (a live run, approvals, connections), also run
   `node scripts/readme-screenshots.mjs`, which drives the demo server.
3. **Look at every screenshot** against the rubric, as each persona. Read the words on screen, not the code.
4. **Walk the five jobs** and note where a persona would stop, guess, or worry.
5. **Verify in code** before reporting anything that a screenshot only suggests (e.g. "no confirmation on delete": check the component).
6. **Rank** findings:
   - **P1, blocks a job or breaks trust** (fix before showing customers)
   - **P2, slows a job or confuses** (fix this cycle)
   - **P3, polish**

## 5. The report

Simple words, short lines; the reader is a founder, not a designer.

1. **Verdict in one line** and an overall score out of 10.
2. **Scores per job** (the five jobs above), each with one sentence.
3. **Top fixes**: P1 then P2 then P3. Each finding has: what the persona sees → why it hurts them → the fix, in one line each, plus the screen and a screenshot.
4. **What already works** (keep it), briefly.
5. **Quick wins**: fixes under an hour each.

Publish it as an artifact when the user asks to share it; otherwise
write it to `docs/ux-audit.md`. Never claim a check you did not run.
