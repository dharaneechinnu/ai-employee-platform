"""Choosing which of a person's AIs does each piece of work.

A person connects several AIs with their own keys (Claude, ChatGPT,
Gemini, their own server, ...). With the model set to "Automatic", each
task goes to the connected AI that suits it best:

1. What kind of task is it? Fast rules decide most cases for free (a
   code block is coding; a very long paste is a long document). Only
   when the rules cannot tell is the cheapest connected AI asked, in one
   tiny call.
2. Which connected AI is best at that kind of task, given the person's
   preference (balanced, best quality, lowest cost, private only)? Each
   model has a small profile: how good it is at each kind of task, how
   fast, how expensive.
3. The ranked list is kept: if the first choice is rate-limited or
   down, the run moves to the next one instead of failing.

Profiles are judgement, not measurement, and model names change, so
matching is by name pattern with a sensible default per provider. A
model nobody has profiled still works; it is just ranked as average.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum


class TaskKind(StrEnum):
    QUICK = "quick"  # a short question with a short answer
    WRITING = "writing"  # drafts, emails, essays, rewrites
    CODING = "coding"  # code, errors, queries
    ANALYSIS = "analysis"  # reasoning, comparing, planning, maths
    LONG = "long"  # a long document or a long conversation to read
    TOOLS = "tools"  # work in the person's apps: mail, calendar, files
    GENERAL = "general"  # none of the above stands out


class Preference(StrEnum):
    BALANCED = "balanced"  # strong AI for hard work, cheap and fast for easy work
    QUALITY = "quality"  # always the most capable
    COST = "cost"  # cheapest that can do the job
    PRIVATE = "private"  # only the person's own server: nothing leaves it


KIND_WORDS: dict[TaskKind, str] = {
    TaskKind.QUICK: "a quick question",
    TaskKind.WRITING: "writing",
    TaskKind.CODING: "coding",
    TaskKind.ANALYSIS: "reasoning and analysis",
    TaskKind.LONG: "a long document",
    TaskKind.TOOLS: "working in your apps",
    TaskKind.GENERAL: "this task",
}


@dataclass(frozen=True, slots=True)
class Profile:
    """1 (weak) to 5 (strong) per kind of task; cost 1 cheap to 5 dear;
    speed 1 slow to 5 instant."""

    quick: int
    writing: int
    coding: int
    analysis: int
    long: int
    tools: int
    cost: int
    speed: int
    private: bool = False

    @property
    def overall(self) -> float:
        skills = (self.quick, self.writing, self.coding, self.analysis, self.long, self.tools)
        return sum(skills) / len(skills)

    def skill(self, kind: TaskKind) -> float:
        if kind is TaskKind.GENERAL:
            return (self.writing + self.analysis + self.quick) / 3
        return float(getattr(self, kind.value))


def _p(q: int, w: int, c: int, a: int, lg: int, t: int, cost: int, speed: int) -> Profile:
    return Profile(q, w, c, a, lg, t, cost, speed)


# Matched against the model name, first match wins, so the specific
# patterns come before the general ones. Works through OpenRouter too
# ("anthropic/claude-sonnet-..." matches the Claude rows).
MODEL_PROFILES: list[tuple[re.Pattern[str], Profile]] = [
    (re.compile(r"claude.*opus|claude-fable|claude-mythos"), _p(4, 5, 5, 5, 5, 5, 5, 2)),
    (re.compile(r"claude.*sonnet"), _p(4, 5, 5, 4, 5, 5, 3, 3)),
    (re.compile(r"claude.*haiku"), _p(4, 3, 3, 3, 4, 4, 1, 5)),
    (re.compile(r"(^|/)o[1-9](-|$)|reason"), _p(2, 3, 5, 5, 3, 3, 4, 1)),
    (re.compile(r"gpt.*(mini|nano)"), _p(4, 3, 3, 3, 3, 4, 1, 4)),
    (re.compile(r"gpt"), _p(4, 4, 4, 4, 4, 5, 3, 3)),
    (re.compile(r"gemini.*pro"), _p(4, 4, 4, 4, 5, 4, 3, 3)),
    (re.compile(r"gemini"), _p(4, 3, 3, 3, 5, 3, 1, 5)),
    (re.compile(r"deepseek.*(r1|reasoner)"), _p(2, 3, 4, 5, 3, 2, 1, 2)),
    (re.compile(r"deepseek"), _p(4, 3, 4, 4, 3, 3, 1, 3)),
    (re.compile(r"mistral.*(large|medium)"), _p(4, 4, 4, 4, 3, 4, 3, 3)),
    (re.compile(r"mistral|ministral"), _p(4, 3, 3, 3, 3, 3, 1, 4)),
    (re.compile(r"llama.*(405|70)|qwen.*(72|32|235)"), _p(4, 3, 4, 4, 3, 3, 2, 3)),
]

# When the model name matches nothing above.
PROVIDER_PROFILES: dict[str, Profile] = {
    "anthropic": _p(4, 5, 5, 4, 5, 5, 3, 3),
    "openai": _p(4, 4, 4, 4, 4, 5, 3, 3),
    "gemini": _p(4, 3, 3, 3, 5, 3, 1, 5),
    "groq": _p(4, 3, 3, 3, 2, 3, 1, 5),
    "deepseek": _p(4, 3, 4, 4, 3, 3, 1, 3),
    "mistral": _p(4, 3, 3, 3, 3, 3, 1, 4),
}
AVERAGE = _p(3, 3, 3, 3, 3, 3, 2, 3)
# Groq serves open models very fast; whatever the model, speed is its point.
FAST_PROVIDERS = {"groq"}
OWN_SERVER = "custom"


def profile_for(provider_key: str, model: str) -> Profile:
    name = model.lower()
    base = next(
        (profile for pattern, profile in MODEL_PROFILES if pattern.search(name)),
        PROVIDER_PROFILES.get(provider_key, AVERAGE),
    )
    if provider_key in FAST_PROVIDERS:
        base = replace(base, speed=5, cost=min(base.cost, 1))
    if provider_key == OWN_SERVER:
        # Your own hardware: no per-call bill, and the data stays home.
        base = replace(base, cost=1, private=True)
    return base


_STRENGTH_WORDS = {
    "writing": "writing",
    "coding": "coding",
    "analysis": "reasoning",
    "long": "long documents",
    "tools": "using apps",
}


def strengths(provider_key: str, model: str) -> list[str]:
    """A few plain words on what Automatic will send to this AI."""
    p = profile_for(provider_key, model)
    words = [word for kind, word in _STRENGTH_WORDS.items() if getattr(p, kind) >= 5]
    if p.speed >= 5:
        words.append("very fast")
    if p.cost <= 1:
        words.append("low cost")
    if p.private:
        words.append("private")
    return words or ["general tasks"]


# --- deciding the kind of task --------------------------------------

_CODE = re.compile(
    r"```|\b(python|javascript|typescript|java|c\+\+|golang|rust|sql|regex|html|css|"
    r"function|bug|stack ?trace|traceback|exception|compile|refactor|unit test|api endpoint|"
    r"def |class |import |select .* from)\b|\b\w+(Error|Exception)\b|is not defined|"
    r"undefined|segfault|null ?pointer|[+\-*/]=",
    re.IGNORECASE,
)
_WRITING = re.compile(
    r"\b(draft|write|rewrite|email|e-mail|letter|essay|blog|post|caption|cover letter|"
    r"proofread|tone|paraphrase|reply to|message to|linkedin|speech|story|poem)\b",
    re.IGNORECASE,
)
_ANALYSIS = re.compile(
    r"\b(why|compare|comparison|analy[sz]e|analysis|evaluate|pros and cons|trade-?offs?|"
    r"plan|strategy|should (i|we)|decide|calculate|prove|solve|derive|estimate|reason|"
    r"research|explain how|step by step)\b|[=+\-*/^]\s*\d",
    re.IGNORECASE,
)
_TOOLS = re.compile(
    r"\b(inbox|gmail|outlook|my (mail|email|calendar|drive|files)|send (an |the )?email|"
    r"schedule|meeting|calendar|invite|crm|deal|database|table)\b",
    re.IGNORECASE,
)
_QUICK = re.compile(r"^(what|who|when|where|which|define|meaning of|is |are |how many)\b", re.I)

LONG_INPUT_CHARS = 6_000
LONG_HISTORY_CHARS = 30_000


def classify_by_rules(text: str, *, history_chars: int = 0) -> TaskKind | None:
    """Most tasks say what they are. None means "not sure"."""
    stripped = text.strip()
    if len(stripped) > LONG_INPUT_CHARS or history_chars > LONG_HISTORY_CHARS:
        return TaskKind.LONG
    if _CODE.search(stripped):
        return TaskKind.CODING
    if _TOOLS.search(stripped):
        return TaskKind.TOOLS
    writing, analysis = bool(_WRITING.search(stripped)), bool(_ANALYSIS.search(stripped))
    if writing and not analysis:
        return TaskKind.WRITING
    if analysis and not writing:
        return TaskKind.ANALYSIS
    if not writing and not analysis and len(stripped) <= 120 and _QUICK.search(stripped):
        return TaskKind.QUICK
    return None


CLASSIFY_PROMPT = (
    "Classify the user's request into exactly one word from this list: quick, writing, "
    "coding, analysis, long, tools, general. quick = a short factual question; writing = "
    "drafting or rewriting text; coding = programming; analysis = reasoning, planning, "
    "comparing or maths; long = reading a long document; tools = acting in email, "
    "calendar or files. Answer with the one word only."
)


def parse_kind(answer: str | None) -> TaskKind:
    word = re.findall(r"[a-z]+", (answer or "").lower())
    for w in word:
        if w in TaskKind._value2member_map_:
            return TaskKind(w)
    return TaskKind.GENERAL


# --- choosing the AI ------------------------------------------------


@dataclass(frozen=True, slots=True)
class Candidate:
    provider_key: str
    model: str
    display_name: str
    failed: bool = False  # its last connection test failed

    @property
    def profile(self) -> Profile:
        return profile_for(self.provider_key, self.model)


@dataclass(frozen=True, slots=True)
class Choice:
    provider_key: str
    model: str
    display_name: str
    kind: TaskKind
    preference: Preference
    reason: str


_HARD = {TaskKind.CODING, TaskKind.ANALYSIS, TaskKind.LONG, TaskKind.TOOLS}

# (weight on skill, weight on cost, weight on speed); cost counts against.
_WEIGHTS: dict[Preference, dict[str, tuple[float, float, float]]] = {
    # Speed only breaks ties: the person asked for the best answer.
    Preference.QUALITY: {"hard": (10, 0, 0.1), "mid": (10, 0, 0.1), "easy": (10, 0, 0.1)},
    # Hard work goes to the strongest AI even when it costs more; easy
    # work to the cheap, fast one.
    Preference.BALANCED: {"hard": (10, -1, 0.5), "mid": (6, -1.5, 0.5), "easy": (2, -3, 3)},
    Preference.COST: {"hard": (3, -4, 1), "mid": (1, -5, 1), "easy": (1, -5, 2)},
    Preference.PRIVATE: {"hard": (10, -1, 0.5), "mid": (6, -1.5, 0.5), "easy": (2, -3, 3)},
}


def rank(candidates: list[Candidate], kind: TaskKind, preference: Preference) -> list[Candidate]:
    """Best first. Connections whose last test failed go last, so they
    are only tried when nothing else is left."""
    pool = candidates
    if preference is Preference.PRIVATE:
        pool = [c for c in candidates if c.profile.private]
    band = "hard" if kind in _HARD else "easy" if kind is TaskKind.QUICK else "mid"
    w_skill, w_cost, w_speed = _WEIGHTS[preference][band]

    def score(c: Candidate) -> tuple[int, float]:
        p = c.profile
        # Overall capability breaks ties between equally good fits, so a
        # simple question under "best quality" still goes to the
        # strongest AI rather than whichever is quickest.
        fit = w_skill * p.skill(kind) + (w_skill / 10) * p.overall
        return (0 if c.failed else 1, fit + w_cost * p.cost + w_speed * p.speed)

    return sorted(pool, key=score, reverse=True)


def explain(choice: Candidate, kind: TaskKind, preference: Preference, others: int) -> str:
    """One short sentence for the person: why this AI did this task."""
    what = KIND_WORDS[kind]
    if others == 0:
        return "your only connected AI"
    if preference is Preference.PRIVATE:
        return f"your own server, best for {what}"
    if preference is Preference.QUALITY:
        return f"most capable of your AIs for {what}"
    if preference is Preference.COST:
        return f"lowest cost of your AIs that handles {what}"
    if kind is TaskKind.QUICK:
        return "fast and low-cost for a quick question"
    return f"best of your AIs for {what}"
