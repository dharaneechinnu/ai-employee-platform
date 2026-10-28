#!/usr/bin/env node
/**
 * A stand-in AI model for recording the live demo. RECORDING AID ONLY:
 * this is not a product feature and nothing in the app depends on it.
 *
 *   node scripts/app-demo/model-server.mjs            # http://localhost:8787/v1
 *
 * There is no real AI key on a recording machine, so this tiny server
 * speaks the OpenAI chat format (`GET /v1/models`, `POST
 * /v1/chat/completions`, tool calls included) and gives scripted answers
 * to the prompts the recording types. It is connected in the real app as
 * "Your own server" on the AI keys page, so everything else on screen is
 * the real product: real runs through the real worker, real tool calls
 * (the calculator, Python, the team helpers), the real approval pause
 * and the real Agent Tree. Only the model's words are scripted.
 *
 * How it decides what to say: the system prompt says who is asking (the
 * lead assistant, or a helper such as the Analyst), the latest user
 * message says which scripted scene it is, and the number of tool
 * results since that message says which step of the scene comes next.
 * Anything it does not recognise gets an honest "scripted demo model"
 * reply instead of a made-up answer.
 *
 * Env: PORT (8787), STANDIN_DELAY_MS (900): how long each answer takes,
 * so the run streams at a believable pace on screen.
 */

import { createServer } from "node:http";

const PORT = Number(process.env.PORT ?? 8787);
const DELAY = Number(process.env.STANDIN_DELAY_MS ?? 900);
const MODEL = "local-demo";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let callSeq = 0;

// ------------------------------------------------------------- replies

const say = (content, wait = 1.4) => ({ content, wait });
const call = (calls, wait = 1) => ({
  calls: calls.map(([name, args]) => ({ name, args })),
  wait,
});

/** The scenes the recording plays, one per prompt it types. */
const LEAD = [
  {
    // Chapter 3: a question the lead splits between two helpers.
    match: /phone plan|₹719|719/i,
    steps: [
      call([
        ["ask_specialist", {
          role: "analyst",
          task: "A phone plan costs ₹719 every 84 days; another costs ₹2,999 for 365 days. "
            + "Work out the cost of each over one year and per month, and which is cheaper.",
        }],
        ["ask_specialist", {
          role: "critic",
          task: "Check this claim with the calculator: paying ₹719 every 84 days costs more "
            + "over a year than paying ₹2,999 once for 365 days.",
        }],
      ], 1.2),
      say(
        "**Take the yearly plan.** It saves you about **₹125 a year**.\n\n"
          + "| Plan | Per year | Per month |\n|---|---|---|\n"
          + "| ₹719 every 84 days | ₹3,124 | ₹260 |\n"
          + "| ₹2,999 for 365 days | ₹2,999 | ₹250 |\n\n"
          + "The Analyst worked out the totals and the Critic checked them: you would recharge "
          + "the 84-day plan about 4.35 times a year. One thing to weigh: the yearly plan is "
          + "₹2,999 up front.",
        2.2,
      ),
    ],
  },
  {
    // Chapter 4: building an agent by chatting.
    match: /\bagent\b/i,
    steps: [
      call([
        ["propose_agent", {
          name: "Morning Plan",
          description: "Every weekday at 8:00, a short plan for the day from your saved notes.",
          instructions: [
            "You are a morning planner for Priya.",
            "Goal: start each weekday with a short, realistic plan for the day.",
            "Who it is for: Priya. Include: deadlines, follow-ups and anything she asked you to remember. Exclude: anything older than a week that is done.",
            "Where to look: her saved notes (recall).",
            "Steps: 1. current_time to get today's date. 2. recall what is due or pending. 3. Pick the three things that matter most today. 4. report_write a short plan.",
            "Rules: never invent details; leave out what is unknown; never delete anything; skip duplicates.",
            "Finish: the three priorities, then anything else worth a glance.",
          ].join("\n"),
          tools: ["current_time", "recall", "report_write"],
          schedule: { frequency: "weekdays", time: "08:00", timezone: "Asia/Kolkata" },
        }],
      ], 1.4),
      say(
        "Here is **Morning Plan**: every weekday at 8:00 it reads your saved notes and gives "
          + "you the three things that matter most that day. Check the card and press "
          + "**Create** when it looks right.",
        1.4,
      ),
    ],
  },
  {
    // Chapter 6: a tool that waits for approval.
    match: /python/i,
    steps: [
      call([
        ["python_run", {
          code: [
            "plans = {\"84-day plan\": (719, 84), \"Yearly plan\": (2999, 365)}",
            "for name, (price, days) in plans.items():",
            "    print(f\"{name}: Rs {price / days * 30:.0f} a month, Rs {price / days * 365:,.0f} a year\")",
          ].join("\n"),
        }],
      ], 1.2),
      say(
        "Python agrees:\n\n```\n84-day plan: Rs 257 a month, Rs 3,124 a year\n"
          + "Yearly plan: Rs 246 a month, Rs 2,999 a year\n```\n\n"
          + "The yearly plan is cheaper by about ₹125 a year.",
        1.6,
      ),
    ],
    // If the run carries the real output, quote it instead of the script.
    quote: (tool) => tool && /stdout|Rs /.test(tool)
      ? `Python agrees:\n\n\`\`\`\n${stdoutOf(tool)}\n\`\`\`\n\nThe yearly plan is cheaper by about ₹125 a year.`
      : null,
  },
];

/** The helpers' parts in the chapter 3 question. */
const HELPERS = {
  analyst: [
    call([
      ["calculator", { expression: "719 * 365 / 84" }],
      ["calculator", { expression: "2999 / 12" }],
    ], 1),
    say(
      "Over a year the 84-day plan costs **₹3,124** (719 × 365 ÷ 84), about ₹260 a month. "
        + "The yearly plan costs **₹2,999**, about ₹250 a month. "
        + "Conclusion: the yearly plan is cheaper by ₹125 a year.",
      1.2,
    ),
  ],
  critic: [
    call([["calculator", { expression: "365 / 84" }]], 1),
    say(
      "The claim holds. A year needs 4.35 recharges of the 84-day plan, so ₹719 × 4.35 ≈ "
        + "₹3,124, which is more than ₹2,999. No errors found.",
      1.1,
    ),
  ],
};

function stdoutOf(text) {
  try {
    const data = JSON.parse(text);
    const out = data.stdout ?? data.output ?? data.data?.stdout;
    if (typeof out === "string") return out.trim();
  } catch {
    /* not JSON: use the text */
  }
  return String(text).replace(/\\n/g, "\n").trim();
}

// ------------------------------------------------------------- choosing

function decide(messages) {
  const system = messages.find((m) => m.role === "system")?.content ?? "";
  const lastUser = messages.map((m) => m.role).lastIndexOf("user");
  const task = String(messages[lastUser]?.content ?? "");
  const after = messages.slice(lastUser + 1);
  const step = after.filter((m) => m.role === "assistant" && m.tool_calls?.length).length;
  const lastTool = [...after].reverse().find((m) => m.role === "tool")?.content;

  if (/^ping$/i.test(task.trim())) return say("pong", 0.2);
  if (system.startsWith("Classify the user's request")) return say("analysis", 0.2);

  const helper = system.match(/^You are an? (analyst|critic)\b/i)?.[1]?.toLowerCase();
  if (helper) return HELPERS[helper][Math.min(step, HELPERS[helper].length - 1)];

  const scene = LEAD.find((s) => s.match.test(task));
  if (scene) {
    const reply = scene.steps[Math.min(step, scene.steps.length - 1)];
    if (reply.content && scene.quote) {
      const quoted = scene.quote(lastTool);
      if (quoted) return { ...reply, content: quoted };
    }
    return reply;
  }
  return say(
    "I am the scripted demo model used to record this video, so I only know the "
      + "prompts in the recording script. Connect a real AI key to ask anything.",
    0.8,
  );
}

// ------------------------------------------------------------- the API

function completion(model, reply) {
  callSeq += 1;
  const toolCalls = (reply.calls ?? []).map((c, i) => ({
    id: `call_${callSeq}_${i}`,
    type: "function",
    function: { name: c.name, arguments: JSON.stringify(c.args) },
  }));
  return {
    id: `chatcmpl-${callSeq}`,
    object: "chat.completion",
    created: Math.floor(Date.now() / 1000),
    model,
    choices: [{
      index: 0,
      message: { role: "assistant", content: reply.content ?? null, ...(toolCalls.length ? { tool_calls: toolCalls } : {}) },
      finish_reason: toolCalls.length ? "tool_calls" : "stop",
    }],
    usage: { prompt_tokens: 900 + 37 * callSeq, completion_tokens: reply.content ? 140 : 60, total_tokens: 0 },
  };
}

/** The same reply as a stream of chunks, for clients that ask for one. */
function streamed(res, body) {
  const choice = body.choices[0];
  res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
  const chunk = (delta, finish = null) =>
    res.write(`data: ${JSON.stringify({ ...body, object: "chat.completion.chunk", choices: [{ index: 0, delta, finish_reason: finish }] })}\n\n`);
  chunk({ role: "assistant" });
  if (choice.message.content) chunk({ content: choice.message.content });
  if (choice.message.tool_calls) chunk({ tool_calls: choice.message.tool_calls.map((c, index) => ({ index, ...c })) });
  chunk({}, choice.finish_reason);
  res.end("data: [DONE]\n\n");
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const send = (code, data) => {
    res.writeHead(code, { "Content-Type": "application/json" });
    res.end(JSON.stringify(data));
  };
  if (req.method === "GET" && /\/models$/.test(url.pathname)) {
    return send(200, { object: "list", data: [{ id: MODEL, object: "model", owned_by: "demo" }] });
  }
  if (req.method === "POST" && /\/chat\/completions$/.test(url.pathname)) {
    let raw = "";
    for await (const part of req) raw += part;
    const body = JSON.parse(raw || "{}");
    const reply = decide(body.messages ?? []);
    await sleep(DELAY * (reply.wait ?? 1));
    const out = completion(body.model ?? MODEL, reply);
    const what = reply.calls?.map((c) => c.name).join(", ") || (reply.content ?? "").slice(0, 50);
    console.log(`[stand-in] ${new Date().toISOString().slice(11, 19)} → ${what}`);
    return body.stream ? streamed(res, out) : send(200, out);
  }
  send(404, { error: { message: "not found" } });
});

server.listen(PORT, () => console.log(`stand-in model on http://localhost:${PORT}/v1 (recording aid)`));
