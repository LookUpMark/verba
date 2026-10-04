"""Task engine: JSON schema per kind + lazy generation on mission open (§7.2)."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..models import Task
from . import generate_structured
from .prompts import tasks_messages

TASK_KINDS: list[str] = ["mc", "translate", "gap", "order", "listening", "speaking"]

_PAYLOAD_SCHEMAS: dict[str, dict] = {
    "mc": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "choices": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 4},
            "answer": {"type": "integer", "minimum": 0, "maximum": 3},
            "why": {"type": "string"},
        },
        "required": ["prompt", "choices", "answer", "why"],
    },
    "gap": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "choices": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 4},
            "answer": {"type": "integer", "minimum": 0, "maximum": 3},
            "why": {"type": "string"},
        },
        "required": ["prompt", "choices", "answer", "why"],
    },
    "translate": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "accepted": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "answerText": {"type": "string"},
            "why": {"type": "string"},
        },
        "required": ["prompt", "accepted", "why"],
    },
    "order": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "words": {"type": "array", "items": {"type": "string"}, "minItems": 3},
            "why": {"type": "string"},
        },
        "required": ["prompt", "words", "why"],
    },
    "listening": {
        "type": "object",
        "properties": {
            "say": {"type": "string"},
            "accepted": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "why": {"type": "string"},
        },
        "required": ["say", "accepted", "why"],
    },
    "speaking": {
        "type": "object",
        "properties": {"say": {"type": "string"}},
        "required": ["say"],
    },
}

TASKS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "minItems": len(TASK_KINDS),
            "maxItems": len(TASK_KINDS),
            "items": {
                "type": "object",
                "properties": {"kind": {"enum": TASK_KINDS}, "payload": {"type": "object"}},
                "required": ["kind", "payload"],
            },
        }
    },
    "required": ["tasks"],
}

_KIND_HINTS: dict[str, str] = {
    "mc": '"choices": 3-4 option strings; "answer": 0-based index of the correct option',
    "gap": '"prompt" contains "___" for the gap; "choices": 3-4 options; "answer": 0-based index of the correct option',
    "translate": '"prompt": the Italian sentence to translate; "accepted": the acceptable English translations',
    "order": '"words": the words of one correct English sentence, in the CORRECT order (3+ words)',
    "listening": '"say": the English sentence the learner hears; "accepted": acceptable transcriptions of it',
    "speaking": '"say": the English sentence the learner must pronounce',
}


def kind_contract() -> str:
    """One textual line per kind, derived from the payload schemas (single source)."""
    lines = []
    for kind in TASK_KINDS:
        schema = _PAYLOAD_SCHEMAS[kind]
        fields = ", ".join(f'"{k}"' for k in schema["required"])
        hint = _KIND_HINTS.get(kind, "")
        lines.append(f'- {kind}: payload keys exactly {fields}' + (f" — {hint}" if hint else ""))
    return "\n".join(lines)


def tasks_schema_for(kinds: list[str]) -> dict:
    """TASKS_SCHEMA sized for a subset request (regeneration of missing kinds)."""
    import copy

    schema = copy.deepcopy(TASKS_SCHEMA)
    arr = schema["properties"]["tasks"]
    arr["minItems"] = len(kinds)
    arr["maxItems"] = len(kinds)
    arr["items"]["properties"]["kind"] = {"enum": kinds}
    return schema


def validate_payload(kind: str, payload: dict) -> dict | None:
    """Structural validation per kind: JSON schema first, then semantics.

    Returns the cleaned payload or None."""
    from . import validate_against_schema

    schema = _PAYLOAD_SCHEMAS.get(kind)
    if schema is None:
        return None
    if validate_against_schema(payload, schema) is not None:
        return None
    if kind in ("mc", "gap") and not 0 <= payload["answer"] < len(payload["choices"]):
        return None
    # Empty text fields must not reach grading: an empty speaking target
    # would grade every answer correct (word_match_ratio on "").
    if kind == "speaking" and not str(payload.get("say") or "").strip():
        return None
    if kind in ("translate", "listening"):
        accepted = payload.get("accepted")
        if not accepted or not any(str(a).strip() for a in accepted):
            return None
    return payload


def _kind_rank(kind: str) -> int:
    """Canonical prototype order: mc, translate, gap, order, listening, speaking.

    Task.id is a random UUID hex, so it must never be used for ordering."""
    return TASK_KINDS.index(kind) if kind in TASK_KINDS else len(TASK_KINDS)


def _sorted_tasks(rows: list[Task]) -> list[Task]:
    return sorted(rows, key=lambda t: _kind_rank(t.kind))


async def _generate_kinds(session: Session, level: str, mission, kinds: list[str]) -> list[Task]:
    """Generate the requested kinds with the contract prompt + validation.

    Small local models sometimes rename payload fields or fumble a kind, so
    the generation repeats for the still-missing kinds only (payload field
    names are stated in the prompt; validation stays the judge of truth).
    """
    contract = kind_contract()
    collected: dict[str, dict] = {}
    for _attempt in range(3):  # 1 full pass + 2 make-up rounds
        missing = [k for k in kinds if k not in collected]
        if not missing:
            break
        try:
            raw = await generate_structured(
                session,
                "generator",
                tasks_messages(level, mission.title, mission.description or mission.title, missing, contract),
                tasks_schema_for(missing),
            )
        except HTTPException:
            if _attempt == 2:
                raise
            continue
        for item in raw.get("tasks", []):
            kind = str(item.get("kind", ""))
            if kind in kinds and kind not in collected:
                payload = validate_payload(kind, item.get("payload") or {})
                if payload is not None:
                    collected[kind] = payload
    return [Task(mission_id=mission.id, kind=k, payload=json_dumps(collected[k])) for k in kinds if k in collected]


async def ensure_tasks(session: Session, level: str, mission) -> list[Task]:
    """Return the mission's tasks, generating them on first open (§7.2).

    A partial set from an older run or a crashed generation is completed on
    the next open: the missing kinds are regenerated instead of being frozen
    away forever. Concurrent first opens are arbitrated by the unique index
    on (mission_id, kind); the loser re-reads instead of duplicating.
    """
    rows = session.exec(select(Task).where(Task.mission_id == mission.id)).all()
    if rows:
        have = {t.kind for t in rows}
        missing = [k for k in TASK_KINDS if k not in have]
        if not missing:
            return _sorted_tasks(rows)
        fresh = await _generate_kinds(session, level, mission, missing)
        return await _persist_tasks(session, mission.id, rows, fresh)

    fresh = await _generate_kinds(session, level, mission, list(TASK_KINDS))
    if not fresh:
        raise HTTPException(status_code=503, detail="model produced no valid tasks; retry mission start")
    return await _persist_tasks(session, mission.id, [], fresh)


async def _persist_tasks(session: Session, mission_id: str, rows: list[Task], fresh: list[Task]) -> list[Task]:
    if not fresh:
        return _sorted_tasks(rows)
    for t in fresh:
        session.add(t)
    try:
        session.commit()
    except IntegrityError:
        # Lost a race against a concurrent mission start (unique index on
        # mission_id+kind): re-read what the winner persisted.
        session.rollback()
        winner = session.exec(select(Task).where(Task.mission_id == mission_id)).all()
        return _sorted_tasks(list(winner))
    for t in fresh:
        session.refresh(t)
    return _sorted_tasks(list(rows) + fresh)


def json_dumps(obj: dict) -> str:
    import json

    return json.dumps(obj)
