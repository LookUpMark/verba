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
    # create_all does not alter existing tables: add the (mission_id, kind)
    # uniqueness to DBs created before the constraint existed. A DB holding
    # pre-existing duplicates can't take the index — keep the app booting.
    with engine.begin() as conn:
        try:
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_mission_kind ON tasks (mission_id, kind)"
            )
        except Exception as e:  # noqa: BLE001 — degraded schema is better than a dead app
            print(f"[verba] could not add tasks uniqueness index: {e}", flush=True)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
