"""Prompt constants. The tutor stays in character; the judge stays analytical."""

TUTOR_SYSTEM = """You are {persona}, a {role} in an English practice conversation.
The learner's CEFR level is {level}: keep YOUR English simple enough for them,
stay in character, ask short questions, never correct grammar yourself.
Reply with 1-3 short sentences only. Scenario: {scenario}."""

JUDGE_SYSTEM = """You are an English teacher's assistant, not a conversation partner.
Given the tutor's last line and the learner's reply, find every real error
(grammar, articles, tense, word choice, word order, mechanics) an Italian
native speaker typically makes. Do not invent errors; ignore style choices
that are correct. `reply_coach` is ONE short encouraging fix sentence.
`suggested_drill` is null unless the learner made at least one error.
Explanations must be one sentence, plain English."""

CURRICULUM_SYSTEM = """You design English lesson missions for a structured path.
Output missions for the requested unit and CEFR level, ordered by difficulty,
each targeting the learner's weak categories when given. 3 to 5 missions,
titles at most 40 characters, no duplicates."""

TASKS_SYSTEM = """You write English exercises for a structured learning app.
Produce exactly the requested number of tasks, one per kind, in order.
Each task must be valid for its kind's schema. Correct English only;
explanations are one short sentence; distractors must be plausible."""


def tutor_messages(persona: str, role: str, level: str, scenario: str, history: list[dict]) -> list[dict]:
    system = TUTOR_SYSTEM.format(persona=persona, role=role, level=level, scenario=scenario)
    out: list[dict] = [{"role": "system", "content": system}]
    trimmed = history[-10:]
    for m in trimmed:
        out.append({"role": "assistant" if m["role"] == "tutor" else "user", "content": m["content"]})
    return out


def judge_messages(tutor_line: str, user_line: str, level: str) -> list[dict]:
    return [
        {"role": "system", "content": JUDGE_SYSTEM},
        {
            "role": "user",
            "content": f"Learner level: {level}\nTutor said: {tutor_line!r}\nLearner replied: {user_line!r}",
        },
    ]


def curriculum_messages(level: str, unit_title: str, weak: list[str], known: list[str]) -> list[dict]:
    weak_txt = ", ".join(weak) if weak else "none recorded"
    known_txt = ", ".join(known[:30]) if known else "nothing yet"
    return [
        {"role": "system", "content": CURRICULUM_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Level: {level}\nUnit: {unit_title}\n"
                f"Learner weak categories: {weak_txt}\nVocabulary already covered: {known_txt}"
            ),
        },
    ]


def tasks_messages(level: str, mission_title: str, objective: str, kinds: list[str]) -> list[dict]:
    return [
        {"role": "system", "content": TASKS_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Level: {level}\nMission: {mission_title}\nObjective: {objective}\n"
                f"Produce {len(kinds)} tasks with kinds in this order: {', '.join(kinds)}."
            ),
        },
    ]


def drills_messages(weak: list[tuple[str, str]]) -> list[dict]:
    examples = "\n".join(f"- [{c}] {w} -> {r}" for c, w, r in weak[:8])
    return [
        {
            "role": "user",
            "content": (
                "Create 3 spaced-repetition drill cards targeting the learner's most frequent errors.\n"
                f"Recent errors:\n{examples}\n"
                'Each card: {"front": "trigger", "back": "the rule", "example": "one correct sentence"}'
            ),
        },
    ]
