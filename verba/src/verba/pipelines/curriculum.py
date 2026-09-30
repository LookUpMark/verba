"""Curriculum pipeline: seeded skeleton + AI unit generation (§7.1)."""

from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import Session, select

from ..models import ErrorRecord, Node
from . import generate_structured
from .prompts import curriculum_messages

CURRICULUM_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "missions": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "maxLength": 40},
                    "objective": {"type": "string"},
                    "target_categories": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "objective"],
            },
        }
    },
    "required": ["missions"],
}

# Hand-seeded skeleton (generated=0) — mirrors the prototype's path so the app
# works before any generation. Missions' tasks are still AI-generated on open.
SKELETON: list[tuple[str, str, list[str]]] = [
    ("A1", "First steps", ["Greetings & introductions", "Meeting new people", "Numbers & prices"]),
    ("A2", "Out & about", ["Last weekend", "At the hotel", "Directions & transport"]),
    ("B1", "Experiences & work", ["Present perfect basics", "Since vs for", "Job interview English"]),
    ("B2", "Nuance", ["Conditionals", "Used to & would"]),
]


def seed_skeleton(session: Session) -> int:
    """Create the A1-B2 skeleton once. Returns how many nodes were created."""
    if session.exec(select(Node).where(Node.kind == "level")).first():
        return 0
    created = 0
    for li, (cefr, unit_title, missions) in enumerate(SKELETON):
        level = Node(language="en", kind="level", cefr=cefr, title=cefr, position=li, generated=False)
        session.add(level)
        session.flush()
        created += 1
        unit = Node(
            language="en", kind="unit", cefr=cefr, title=unit_title, parent_id=level.id, position=0, generated=False
        )
        session.add(unit)
        session.flush()
        created += 1
        for mi, title in enumerate(missions):
            session.add(
                Node(
                    language="en",
                    kind="mission",
                    cefr=cefr,
                    title=title,
                    description=f"{cefr} practice: {unit_title.lower()}",
                    parent_id=unit.id,
                    position=mi,
                    generated=False,
                )
            )
            created += 1
    session.commit()
    return created


def weak_categories(session: Session) -> list[str]:
    rows = session.exec(select(ErrorRecord).where(ErrorRecord.resolved.is_(False))).all()
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.category] = counts.get(r.category, 0) + 1
    return [c for c, _ in sorted(counts.items(), key=lambda kv: -kv[1])]


async def generate_unit(session: Session, unit: Node) -> list[Node]:
    """Replace-forward: append new AI missions to a unit (§7.1)."""
    if unit.kind != "unit":
        raise HTTPException(status_code=400, detail="not a unit")
    existing = session.exec(select(Node).where(Node.parent_id == unit.id)).all()
    if not existing:
        raise HTTPException(status_code=404, detail="unit not found")
    level = unit.cefr or "A2"
    known = [t for (t,) in session.exec(select(Node.title).where(Node.kind == "mission")).all()]
    raw = await generate_structured(
        session,
        "generator",
        curriculum_messages(level, unit.title, weak_categories(session), known),
        CURRICULUM_SCHEMA,
    )
    existing_titles = {n.title.lower() for n in existing}
    out: list[Node] = []
    for i, m in enumerate(raw.get("missions", [])):
        title = str(m.get("title", "")).strip()
        if not title or title.lower() in existing_titles:
            continue
        node = Node(
            language="en",
            kind="mission",
            cefr=level,
            title=title,
            description=str(m.get("objective", "")),
            parent_id=unit.id,
            position=len(existing) + i,
            generated=True,
        )
        session.add(node)
        out.append(node)
    unit.regen_count += 1
    session.add(unit)
    if not out:
        raise HTTPException(status_code=503, detail="model produced no new missions; retry")
    session.commit()
    for n in out:
        session.refresh(n)
    return out
