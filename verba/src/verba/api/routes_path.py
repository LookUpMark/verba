"""Path: curriculum tree, placement, unit generation (§6 → Path screen)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from ..db import get_session
from ..models import Node
from ..pipelines.curriculum import generate_unit
from .helpers import completed_ids, profile_get, profile_set

router = APIRouter()


def _mission_rows(session: Session) -> list[Node]:
    return session.exec(select_missions()).all()


def select_missions():
    from sqlmodel import select

    return select(Node).where(Node.kind == "mission").order_by(Node.parent_id, Node.position)


@router.get("/path")
def get_path(session: Session = Depends(get_session)) -> dict[str, Any]:
    done = set(completed_ids(session))
    levels = session.exec(
        _level_query()
    ).all()
    tree: list[dict[str, Any]] = []
    current_assigned = False
    missions_all: list[Node] = []
    for level in levels:
        units = session.exec(_children_query(level.id)).all()
        unit_out: list[dict[str, Any]] = []
        for unit in units:
            missions = session.exec(_children_query(unit.id)).all()
            missions_all.extend(missions)
            mission_out = []
            for m in missions:
                if m.id in done:
                    state = "done"
                elif not current_assigned:
                    state = "current"
                    current_assigned = True
                else:
                    state = "locked"
                mission_out.append({"id": m.id, "title": m.title, "state": state, "generated": m.generated})
            unit_out.append({"id": unit.id, "title": unit.title, "missions": mission_out})
        tree.append({"id": level.id, "cefr": level.cefr, "title": level.title, "units": unit_out})
    current = next((m["id"] for u in tree for uu in u["units"] for m in uu["missions"] if m["state"] == "current"), None)
    return {
        "tree": tree,
        "current": current,
        "level": profile_get(session, "level"),
        "xp": int(profile_get(session, "xp", "0")),
        "streak": int(profile_get(session, "streak", "0")),
        "missions_done": len(done),
    }


def _level_query():
    from sqlmodel import select

    return select(Node).where(Node.kind == "level").order_by(Node.position)


def _children_query(parent_id: str):
    from sqlmodel import select

    return select(Node).where(Node.parent_id == parent_id).order_by(Node.position)


class PlacementBody(BaseModel):
    correct: int
    questions: int = 5


PLACEMENT_MAP = {"A1": 0, "A2": 3, "B1": 5, "B2": 8}


@router.post("/onboarding/placement")
def placement(body: PlacementBody, session: Session = Depends(get_session)) -> dict[str, Any]:
    n = max(0, min(body.correct, body.questions))
    level = "A1" if n <= 1 else "A2" if n <= 3 else "B1" if n == 4 else "B2"
    unlock = PLACEMENT_MAP[level]
    ids = [m.id for m in _mission_rows(session)][:unlock]
    profile_set(session, "level", level)
    profile_set(session, "completed_ids", __import__("json").dumps(ids))
    profile_set(session, "onboarded", "1")
    session.commit()
    return {"level": level, "unlocked": len(ids)}


class GoalBody(BaseModel):
    target: int


@router.post("/onboarding/goal")
def set_goal(body: GoalBody, session: Session = Depends(get_session)) -> dict[str, int]:
    profile_set(session, "goal_target", str(max(5, min(200, body.target))))
    session.commit()
    return {"goal_target": max(5, min(200, body.target))}


@router.post("/path/units/{unit_id}/generate")
async def regenerate_unit(unit_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    unit = session.get(Node, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="unit not found")
    created = await generate_unit(session, unit)
    return {"created": [{"id": n.id, "title": n.title, "generated": True} for n in created]}
