"""Contract tests for the FSRS-lite scheduler (§8)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from verba.models import SrsCard
from verba.services.srs import RETIRE_AT, schedule


def _card(stability: float = 1.0) -> SrsCard:
    return SrsCard(source="seed", front="f", back="b", example="e", stability=stability)


def test_good_grows_stability_and_schedules_forward():
    card = _card(2.0)
    before = datetime.now(timezone.utc)
    schedule(card, "good")
    assert card.stability > 2.0
    due = datetime.fromisoformat(card.due_at)
    assert due > before + timedelta(hours=23)


def test_again_resets_and_is_due_soon():
    card = _card(5.0)
    schedule(card, "again")
    assert card.stability == 0.0
    due = datetime.fromisoformat(card.due_at)
    assert due <= datetime.now(timezone.utc) + timedelta(minutes=11)


def test_easy_grows_fastest_and_retirement():
    card = _card(20.0)
    schedule(card, "easy")
    assert card.stability >= RETIRE_AT
    assert card.retired is True


def test_unknown_grade_falls_back_to_good():
    card = _card(1.0)
    schedule(card, "banana")
    assert card.stability > 1.0
