"""Profile key/value helpers shared by routers."""

from __future__ import annotations

import json

from sqlmodel import Session

from ..models import ProfileEntry


def profile_get(session: Session, key: str, default: str | None = None) -> str | None:
    row = session.get(ProfileEntry, key)
    return row.value if row else default


def profile_set(session: Session, key: str, value: str) -> None:
    row = session.get(ProfileEntry, key)
    if row is None:
        row = ProfileEntry(key=key)
    row.value = value
    session.add(row)


def profile_int(session: Session, key: str, default: int = 0) -> int:
    raw = profile_get(session, key)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def completed_ids(session: Session) -> list[str]:
    raw = profile_get(session, "completed_ids", "[]")
    try:
        return list(json.loads(raw or "[]"))
    except json.JSONDecodeError:
        return []


def bump_daily(session: Session, xp: int = 0, missions: int = 0, errors: int = 0) -> None:
    from datetime import datetime, timezone

    from ..models import DailyStat

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = session.get(DailyStat, day)
    if row is None:
        row = DailyStat(day=day)
    row.xp += xp
    row.missions += missions
    row.errors += errors
    session.add(row)
