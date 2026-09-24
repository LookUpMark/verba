"""FSRS-lite scheduler — a documented approximation, not the full FSRS crate.

Grades: again / hard / good / easy. Stability grows with successful recalls;
cards retire at stability >= RETIRE_AT. Upgrade path: swap for an FSRS
implementation without touching callers (ponytail: simplest correct v1).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

RETIRE_AT = 21.0
DAY = timedelta(days=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def schedule(card, grade: str) -> None:
    grade = grade if grade in ("again", "hard", "good", "easy") else "good"
    stability = card.stability
    if grade == "again":
        card.stability = 0.0
        card.difficulty = min(10.0, card.difficulty + 0.6)
        due = _now() + timedelta(minutes=10)
    elif grade == "hard":
        card.stability = max(0.5, stability * 1.2)
        card.difficulty = min(10.0, card.difficulty + 0.2)
        due = _now() + max(timedelta(hours=8), DAY * card.stability * 0.8)
    elif grade == "easy":
        card.stability = max(1.0, stability * 2.8 + 0.4)
        card.difficulty = max(1.0, card.difficulty - 0.3)
        due = _now() + DAY * card.stability * 2.8
    else:  # good
        card.stability = max(1.0, stability * 2.0 + 0.4)
        due = _now() + DAY * card.stability * 2.0

    card.last_grade = grade
    card.due_at = due.isoformat(timespec="seconds")
    if card.stability >= RETIRE_AT:
        card.retired = True
