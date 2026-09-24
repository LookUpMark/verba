"""Judge: deterministic pre-pass + LLM judge, merged and persisted (§7.3)."""

from __future__ import annotations

from sqlmodel import Session

from ..models import ErrorRecord, SrsCard
from . import generate_structured
from .prompts import judge_messages
from .rules import rules_scan

JUDGE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "wrong": {"type": "string"},
                    "right": {"type": "string"},
                    "explanation": {"type": "string"},
                    "severity": {"type": "integer", "minimum": 1, "maximum": 3},
                },
                "required": ["category", "wrong", "right", "explanation"],
            },
        },
        "reply_coach": {"type": "string"},
        "suggested_drill": {
            "type": ["object", "null"],
            "properties": {
                "front": {"type": "string"},
                "back": {"type": "string"},
                "example": {"type": "string"},
            },
        },
    },
    "required": ["score", "errors", "reply_coach"],
}

VALID_CATEGORIES = {"grammar", "articles", "tense", "word_choice", "word_order", "mechanics", "speaking", "listening"}


def _norm_error(e: dict) -> dict | None:
    if not isinstance(e, dict):
        return None
    wrong, right, explanation = str(e.get("wrong", "")).strip(), str(e.get("right", "")).strip(), str(e.get("explanation", "")).strip()
    if not (wrong and right and explanation):
        return None
    category = str(e.get("category", "grammar")).lower()
    if category not in VALID_CATEGORIES:
        category = "grammar"
    severity = e.get("severity", 2)
    try:
        severity = max(1, min(3, int(severity)))
    except (TypeError, ValueError):
        severity = 2
    return {"category": category, "wrong": wrong, "right": right, "explanation": explanation, "severity": severity}


def _merge(pre: list[dict], llm: list[dict]) -> list[dict]:
    """Union, deduped on normalized `wrong`; deterministic findings win."""
    out: list[dict] = list(pre)
    seen = {(e["wrong"].lower()) for e in pre}
    for e in llm:
        key = e["wrong"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out[:8]


async def judge_message(session: Session, level: str, tutor_line: str, user_line: str, source: str = "tutor") -> dict:
    """Returns the diagnosis dict and persists errors + suggested drill."""
    pre = rules_scan(user_line)

    llm_errors: list[dict] = []
    reply_coach = ""
    drill: dict | None = None
    try:
        raw = await generate_structured(session, "judge", judge_messages(tutor_line, user_line, level), JUDGE_SCHEMA)
        llm_errors = [e for e in (_norm_error(x) for x in raw.get("errors", [])) if e]
        reply_coach = str(raw.get("reply_coach", "")).strip()
        raw_drill = raw.get("suggested_drill")
        if isinstance(raw_drill, dict) and raw_drill.get("front") and raw_drill.get("back"):
            drill = {"front": str(raw_drill["front"]), "back": str(raw_drill["back"]), "example": str(raw_drill.get("example", ""))}
        # deterministic findings veto LLM claims about the same span
        llm_errors = _merge([], llm_errors)
        errors = _merge(pre, llm_errors)
        score = int(raw.get("score", 100))
        score = max(40, min(100, score))
        if pre and score > 95:
            score = min(score, 100 - 12 * len(pre))
    except Exception:
        # degraded: deterministic pre-pass only (architecture.md §7.3)
        errors = pre
        score = max(40, 100 - 14 * len(errors))
        if len(user_line.split()) < 4:
            score = max(40, score - 10)

    diagnosis = {"score": score, "errors": errors, "reply_coach": reply_coach}

    for e in errors:
        session.add(
            ErrorRecord(
                category=e["category"],
                wrong=e["wrong"],
                right=e["right"],
                explanation=e["explanation"],
                source=source,
                severity=e["severity"],
            )
        )
    if drill:
        session.add(SrsCard(source="seed", front=drill["front"], back=drill["back"], example=drill.get("example")))
    session.commit()
    return diagnosis
