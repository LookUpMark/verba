"""SQLite engine + session factory (sync engine; FastAPI runs handlers in a threadpool)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401  — imported for table registration
from .config import settings

engine = create_engine(f"sqlite:///{settings.db_path}", echo=False)


def init_db() -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
