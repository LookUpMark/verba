"""Lessons: mission start (lazy task generation), attempt grading, completion."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from ..db import get_session
from ..models import Attempt, ErrorRecord, Node, Task
from ..pipelines.tasks import ensure_tasks
from ..services.grading import CATEGORY_BY_KIND, grade_task
from .helpers import bump_daily, completed_ids, profile_get, profile_int, profile_set

router = APIRouter()


@router.post("/missions/{mission_id}/start")
async def start_mission(mission_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    mission = session.get(Node, mission_id)
    if mission is None or mission.kind != "mission":
        raise HTTPException(status_code=404, detail="mission not found")
    level = mission.cefr or "A2"
    tasks = await ensure_tasks(session, level, mission)
    return {
        "mission": {"id": mission.id, "title": mission.title, "level": level},
        "tasks": [{"id": t.id, "kind": t.kind, "payload": json.loads(t.payload)} for t in tasks],
    }


class AttemptBody(BaseModel):
    task_id: str
    answer: str
    latency_ms: int | None = None


@router.post("/attempts")
def submit_attempt(body: AttemptBody, session: Session = Depends(get_session)) -> dict[str, Any]:
    task = session.get(Task, body.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    is_correct, correct_text = grade_task(task.kind, task.payload, body.answer)
    session.add(
        Attempt(task_id=task.id, is_correct=is_correct, latency_ms=body.latency_ms, answer=body.answer[:2000])
    )
    payload = json.loads(task.payload)
    if not is_correct:
        session.add(
            ErrorRecord(
                category=CATEGORY_BY_KIND.get(task.kind, "grammar"),
                wrong=f"you said: {body.answer[:200]}",
                right=correct_text,
                explanation=str(payload.get("why", "Review this pattern.")),
                source="lesson",
                severity=2,
            )
        )
    done = profile_int(session, "tasks_done") + 1
    correct_total = profile_int(session, "tasks_correct") + (1 if is_correct else 0)
    profile_set(session, "tasks_done", str(done))
    profile_set(session, "tasks_correct", str(correct_total))
    session.commit()
    return {
        "correct": is_correct,
        "correct_answer": correct_text,
        "why": payload.get("why"),
        "category": CATEGORY_BY_KIND.get(task.kind, "grammar"),
    }


class CompleteBody(BaseModel):
    correct: int
    total: int


@router.post("/missions/{mission_id}/complete")
def complete_mission(mission_id: str, body: CompleteBody, session: Session = Depends(get_session)) -> dict[str, Any]:
    mission = session.get(Node, mission_id)
    if mission is None or mission.kind != "mission":
        raise HTTPException(status_code=404, detail="mission not found")
    # Score from the attempts actually recorded for this mission's tasks: the
    # client body is trusted only as a fallback when no attempt exists, so
    # forged correct/total values cannot inflate XP or accuracy.
    from sqlmodel import select

    task_ids = list(session.exec(select(Task.id).where(Task.mission_id == mission_id)).all())
    attempts = list(session.exec(select(Attempt).where(Attempt.task_id.in_(task_ids))).all()) if task_ids else []
    total = len(attempts)
    correct = sum(1 for a in attempts if a.is_correct)
    if total == 0:
        total = max(1, body.total)
        correct = max(0, min(body.correct, total))
    acc = max(0, min(100, round(100 * correct / total)))
    gained = 20 + round(acc / 5)

    done = completed_ids(session)
    if mission_id not in done:
        done.append(mission_id)
    profile_set(session, "completed_ids", json.dumps(done))
    profile_set(session, "xp", str(profile_int(session, "xp") + gained))

    done_today = int(profile_get(session, "goal_done", "0")) + 1
    profile_set(session, "goal_done", str(done_today))
    bump_daily(session, xp=gained, missions=1, errors=total - correct)
    session.commit()

    next_mission = None
    for m in _ordered_missions(session):
        if m.id == mission_id:
            continue
        if m.id not in done:
            next_mission = {"id": m.id, "title": m.title}
            break
    return {"xp_gained": gained, "accuracy": acc, "next": next_mission}


def _ordered_missions(session: Session) -> list[Node]:
    from sqlmodel import select

    return list(session.exec(select(Node).where(Node.kind == "mission").order_by(Node.parent_id, Node.position)).all())
