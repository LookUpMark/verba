"""Task engine: JSON schema per kind + lazy generation on mission open (§7.2)."""

from __future__ import annotations

from fastapi import HTTPException
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
    """Minimal structural validation per kind; returns the cleaned payload or None."""
    schema = _PAYLOAD_SCHEMAS.get(kind)
    if schema is None:
        return None
    for key in schema.get("required", []):
        if key not in payload:
            return None
    if kind in ("mc", "gap"):
        if not isinstance(payload.get("choices"), list) or not isinstance(payload.get("answer"), int):
            return None
        if not 0 <= payload["answer"] < len(payload["choices"]):
            return None
    if kind == "order" and not isinstance(payload.get("words"), list):
        return None
    if kind in ("translate", "listening") and not isinstance(payload.get("accepted"), list):
        return None
    return payload


async def ensure_tasks(session: Session, level: str, mission) -> list[Task]:
    """Return the mission's tasks, generating them on first open (§7.2).

    Small local models sometimes rename payload fields or fumble a kind, so
    the generation repeats for the missing kinds only (payload field names
    are stated in the prompt; validation stays the judge of truth).
    """
    rows = session.exec(select(Task).where(Task.mission_id == mission.id).order_by(Task.id)).all()
    if rows:
        return rows

    contract = kind_contract()
    collected: dict[str, dict] = {}
    for _attempt in range(3):  # 1 full pass + 2 make-up rounds for missing kinds
        missing = [k for k in TASK_KINDS if k not in collected]
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
            if kind not in TASK_KINDS or kind in collected:
                continue
            payload = validate_payload(kind, item.get("payload") or {})
            if payload is not None:
                collected[kind] = payload

    if not collected:
        raise HTTPException(status_code=503, detail="model produced no valid tasks; retry mission start")
    out = [Task(mission_id=mission.id, kind=k, payload=json_dumps(collected[k])) for k in TASK_KINDS if k in collected]
    for t in out:
        session.add(t)
    session.commit()
    for t in out:
        session.refresh(t)
    return out


def json_dumps(obj: dict) -> str:
    import json

    return json.dumps(obj)
