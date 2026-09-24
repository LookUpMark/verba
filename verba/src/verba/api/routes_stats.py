"""Stats: overview, daily chart, errors by category (§6 → Stats screen)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..db import get_session
from ..models import Attempt, DailyStat, ErrorRecord, Node, ProfileEntry, SrsCard
from .helpers import completed_ids, profile_get, profile_int

router = APIRouter()


@router.get("/stats/overview")
def overview(session: Session = Depends(get_session)) -> dict[str, Any]:
    tasks_done = profile_int(session, "tasks_done")
    tasks_correct = profile_int(session, "tasks_correct")
    accuracy = round(100 * tasks_correct / tasks_done) if tasks_done else None
    return {
        "xp": profile_int(session, "xp"),
        "streak": profile_int(session, "streak"),
        "missions_done": len(completed_ids(session)),
        "accuracy": accuracy,
        "tasks_done": tasks_done,
        "tasks_correct": tasks_correct,
        "level": profile_get(session, "level"),
    }


@router.get("/stats/daily")
def daily(days: int = 14, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    days = max(1, min(90, days))
    start = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    rows = session.exec(select(DailyStat).where(DailyStat.day >= start).order_by(DailyStat.day)).all()
    by_day = {r.day: {"xp": r.xp, "missions": r.missions, "errors": r.errors} for r in rows}
    out = []
    for i in range(days):
        d = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        out.append({"day": d, **by_day.get(d, {"xp": 0, "missions": 0, "errors": 0})})
    return out


@router.get("/stats/errors")
def errors_by_category(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.exec(select(ErrorRecord)).all()
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.category] = counts.get(r.category, 0) + 1
    return [
        {"category": c, "count": n}
        for c, n in sorted(counts.items(), key=lambda kv: -kv[1])
    ]


@router.get("/stats/profile-keys")
def profile_keys(session: Session = Depends(get_session)) -> dict[str, str]:
    return {p.key: p.value for p in session.exec(select(ProfileEntry)).all()}


@router.get("/stats/library")
def library(session: Session = Depends(get_session)) -> dict[str, Any]:
    missions = session.exec(select(Node).where(Node.kind == "mission")).all()
    cards = session.exec(select(SrsCard)).all()
    return {
        "missions_total": len(missions),
        "srs_cards": len(cards),
        "srs_retired": sum(1 for c in cards if c.retired),
    }
