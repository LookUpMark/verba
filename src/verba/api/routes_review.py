"""Review: SRS queue, grading, AI drill generation (§6 → Review screen)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..api.helpers import bump_daily
from ..db import get_session
from ..models import SrsCard
from ..pipelines import generate_structured
from ..pipelines.prompts import drills_messages
from ..services.srs import schedule

router = APIRouter()


def _due_rows(session: Session) -> list[SrsCard]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = session.exec(
        select(SrsCard).where(SrsCard.retired.is_(False)).order_by(SrsCard.due_at)
    ).all()
    return [r for r in rows if r.due_at <= now]


@router.get("/review/queue")
def queue(session: Session = Depends(get_session)) -> dict[str, Any]:
    rows = _due_rows(session)
    return {
        "due": [{"id": c.id, "front": c.front, "back": c.back, "example": c.example, "stability": c.stability} for c in rows],
        "count": len(rows),
    }


class GradeBody(BaseModel):
    card_id: str
    grade: Literal["again", "hard", "good", "easy"]


@router.post("/review/grade")
def grade(body: GradeBody, session: Session = Depends(get_session)) -> dict[str, Any]:
    card = session.get(SrsCard, body.card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="card not found")
    schedule(card, body.grade)
    session.add(card)
    bump_daily(session)  # a graded card counts toward the daily goal
    session.commit()
    return {"due_at": card.due_at, "retired": card.retired, "stability": card.stability}


@router.post("/review/generate")
async def generate_drills(session: Session = Depends(get_session)) -> dict[str, Any]:
    """LLM drills from the learner's most frequent errors; 503 in degraded mode."""
    from sqlmodel import select as _select

    from ..models import ErrorRecord

    rows = session.exec(_select(ErrorRecord).order_by(ErrorRecord.created_at.desc())).all()
    weak: list[tuple[str, str, str]] = [(r.category, r.wrong, r.right) for r in rows[:20]]
    if not weak:
        return {"created": 0, "detail": "No errors recorded yet — complete a mission or a scenario first."}
    raw = await generate_structured(session, "generator", drills_messages(weak), _DRILLS_SCHEMA)
    created: list[dict] = []
    for c in raw.get("cards", []):
        if not (c.get("front") and c.get("back")):
            continue
        card = SrsCard(
            source="error:llm", front=str(c["front"])[:200], back=str(c["back"])[:500], example=str(c.get("example", ""))
        )
        session.add(card)
        created.append({"front": card.front})
    session.commit()
    return {"created": len(created), "cards": created}


_DRILLS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "front": {"type": "string"},
                    "back": {"type": "string"},
                    "example": {"type": "string"},
                },
                "required": ["front", "back"],
            },
        }
    },
    "required": ["cards"],
}
