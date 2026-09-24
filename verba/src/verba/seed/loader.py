"""One-time seed: curriculum skeleton + starter SRS deck."""

from __future__ import annotations

from sqlmodel import Session, select

from ..models import Node, SrsCard
from ..pipelines.curriculum import seed_skeleton
from .content import SEED_CARDS


def seed_all(session: Session) -> dict:
    nodes = seed_skeleton(session)
    cards = 0
    if not session.exec(select(SrsCard)).first():
        for c in SEED_CARDS:
            session.add(SrsCard(source="seed", **c))
            cards += 1
        session.commit()
    return {"nodes": nodes, "srs_cards": cards}
