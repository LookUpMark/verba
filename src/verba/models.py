"""SQLModel tables — the schema of architecture.md §4."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def uid() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Node(SQLModel, table=True):
    """Curriculum tree row. depth 0 = level, 1 = unit, 2 = mission."""

    __tablename__ = "nodes"

    id: str = Field(primary_key=True, default_factory=uid)
    language: str = Field(default="en", index=True)
    kind: str  # level | unit | mission
    cefr: str | None = None
    title: str
    description: str | None = None
    parent_id: str | None = Field(default=None, foreign_key="nodes.id", index=True)
    position: int = 0
    generated: bool = True
    regen_count: int = 0
    created_at: str = Field(default_factory=now_iso)


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: str = Field(primary_key=True, default_factory=uid)
    mission_id: str = Field(foreign_key="nodes.id", index=True)
    kind: str  # mc | translate | gap | order | listening | speaking
    payload: str  # JSON, schema per kind (architecture.md §7.2)
    difficulty: float = 0.5
    created_at: str = Field(default_factory=now_iso)


class Attempt(SQLModel, table=True):
    __tablename__ = "attempts"

    id: str = Field(primary_key=True, default_factory=uid)
    task_id: str | None = Field(default=None, foreign_key="tasks.id", index=True)
    session_id: str | None = None
    is_correct: bool
    latency_ms: int | None = None
    answer: str | None = None
    created_at: str = Field(default_factory=now_iso)


class ErrorRecord(SQLModel, table=True):
    """A diagnosed error — the learner's real profile."""

    __tablename__ = "errors"

    id: str = Field(primary_key=True, default_factory=uid)
    category: str = Field(index=True)  # grammar | articles | tense | word_choice | word_order | mechanics | speaking | listening
    wrong: str
    right: str
    explanation: str
    source: str  # lesson | tutor | review
    severity: int = 1  # 1 minor .. 3 core
    resolved: bool = Field(default=False, index=True)
    created_at: str = Field(default_factory=now_iso)


class SrsCard(SQLModel, table=True):
    __tablename__ = "srs_cards"

    id: str = Field(primary_key=True, default_factory=uid)
    front: str
    back: str
    example: str | None = None
    source: str = "seed"  # seed | error:<error_id>
    stability: float = 0.0
    difficulty: float = 5.0
    due_at: str = Field(default_factory=now_iso, index=True)
    last_grade: str | None = None  # again | hard | good | easy
    retired: bool = False


class ChatSession(SQLModel, table=True):
    __tablename__ = "chat_sessions"

    id: str = Field(primary_key=True, default_factory=uid)
    language: str = "en"
    scenario: str
    persona: str
    level: str
    status: str = "active"  # active | done | abandoned
    created_at: str = Field(default_factory=now_iso)


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"

    id: str = Field(primary_key=True, default_factory=uid)
    session_id: str = Field(foreign_key="chat_sessions.id", index=True)
    role: str  # tutor | user | system
    content: str
    diagnosis: str | None = None  # JSON judge output for user messages (§7.3)
    created_at: str = Field(default_factory=now_iso)


class DailyStat(SQLModel, table=True):
    __tablename__ = "daily_stats"

    day: str = Field(primary_key=True)  # YYYY-MM-DD
    xp: int = 0
    missions: int = 0
    errors: int = 0


class ProfileEntry(SQLModel, table=True):
    __tablename__ = "profile"

    key: str = Field(primary_key=True)
    value: str


class RuntimeRecord(SQLModel, table=True):
    """A local inference runtime and what discovery found on it."""

    __tablename__ = "runtimes"

    id: str = Field(primary_key=True)  # lmstudio | ollama | mlx | hf
    name: str
    endpoint: str
    status: str = "missing"  # detected | missing
    models: str = "[]"  # JSON list of {id, fmt, size_bytes}


class RoleAssignment(SQLModel, table=True):
    __tablename__ = "role_assignments"

    role: str = Field(primary_key=True)  # tutor | judge | generator
    runtime: str = Field(foreign_key="runtimes.id")
    model_id: str
