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
    """Return the mission's tasks, generating them on first open (§7.2)."""
    rows = session.exec(select(Task).where(Task.mission_id == mission.id).order_by(Task.id)).all()
    if rows:
        return rows

    kinds = list(TASK_KINDS)
    raw = await generate_structured(
        session,
        "generator",
        tasks_messages(level, mission.title, mission.description or mission.title, kinds),
        TASKS_SCHEMA,
    )
    out: list[Task] = []
    for item in raw.get("tasks", []):
        kind = str(item.get("kind", ""))
        if kind not in TASK_KINDS:
            continue
        payload = validate_payload(kind, item.get("payload") or {})
        if payload is None:
            continue
        out.append(Task(mission_id=mission.id, kind=kind, payload=json_dumps(payload)))
    # keep prototype order: mc, translate, gap, order, listening, speaking
    out.sort(key=lambda t: TASK_KINDS.index(t.kind))
    if not out:
        raise HTTPException(status_code=503, detail="model produced no valid tasks; retry mission start")
    for t in out:
        session.add(t)
    session.commit()
    for t in out:
        session.refresh(t)
    return out


def json_dumps(obj: dict) -> str:
    import json

    return json.dumps(obj)
