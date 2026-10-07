"""Tutor chat: scenarios, sessions, message + SSE stream (§6, §7.3)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import engine, get_session
from ..models import ChatMessage, ChatSession, RuntimeRecord
from ..pipelines.judge import judge_message
from ..pipelines.prompts import tutor_messages
from ..providers.base import provider_for, resolve_roles
from ..seed.content import SCENARIOS

router = APIRouter()


@router.get("/chat/scenarios")
def scenarios() -> list[dict[str, Any]]:
    return SCENARIOS


class SessionBody(BaseModel):
    scenario: str


@router.post("/chat/sessions")
def create_session(body: SessionBody, session: Session = Depends(get_session)) -> dict[str, Any]:
    sc = next((s for s in SCENARIOS if s["id"] == body.scenario), None)
    if sc is None:
        raise HTTPException(status_code=404, detail="unknown scenario")
    cs = ChatSession(language="en", scenario=sc["id"], persona=f"{sc['persona']} — {sc['role']}", level=sc["level"])
    session.add(cs)
    session.commit()
    session.refresh(cs)
    return {"id": cs.id, "scenario": sc, "persona": sc["persona"], "role": sc["role"], "level": sc["level"]}


def _history(session: Session, session_id: str) -> list[dict]:
    rows = session.exec(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    ).all()
    # system rows are judge metadata, not conversation turns — keep them out
    # of the tutor's context or the model reads its own diagnosis JSON as
    # learner speech on the next turn.
    return [{"role": m.role, "content": m.content} for m in rows if m.role in ("user", "tutor")]


def _last_coach(session: Session, session_id: str) -> str:
    """The most recent judge reply_coach for this session, if any (§8)."""
    rows = session.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.role == "system")
        .order_by(ChatMessage.created_at.desc())
    ).all()
    for row in rows:
        try:
            coach = str(json.loads(row.content).get("reply_coach") or "").strip()
        except (json.JSONDecodeError, AttributeError):
            continue
        if coach:
            return coach
    return ""


def _tutor_target(session: Session) -> tuple[str, str, str] | None:
    roles = resolve_roles(session)
    target = roles.get("tutor")
    if target is None:
        return None
    runtime = session.get(RuntimeRecord, target["runtime"])
    if runtime is None:
        return None
    return runtime.id, runtime.endpoint, target["model"]


def _sse(event: str, data: dict | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


@router.get("/chat/sessions/{session_id}/stream")
async def stream_session(session_id: str, db: Session = Depends(get_session)) -> StreamingResponse:
    cs = db.get(ChatSession, session_id)
    if cs is None:
        raise HTTPException(status_code=404, detail="session not found")

    async def gen() -> AsyncIterator[str]:
        history = _history(db, session_id)
        pending_user = bool(history) and history[-1]["role"] == "user"
        target = _tutor_target(db)
        if target is None:
            yield _sse("error", {"detail": "No tutor model detected. Start LM Studio or Ollama and re-scan runtimes."})
            yield _sse("done", {"status": "error"})
            return

        tutor_line = ""
        try:
            runtime = db.get(RuntimeRecord, target[0])
            provider = provider_for(target[0], runtime.endpoint, target[2])
            scenario_desc = next((s["description"] for s in SCENARIOS if s["id"] == cs.scenario), cs.scenario)
            messages = tutor_messages(cs.persona, cs.scenario, cs.level, scenario_desc, history)
            coach = _last_coach(db, session_id)
            if coach:
                # §8: reply_coach feeds the tutor's next-turn prefix. Injected as
                # a hint — the tutor weaves the fix in naturally and never
                # mentions the judge (that's the diagnosis card's job).
                messages.insert(1, {"role": "system", "content": f"Coaching hint for your next reply — weave the fix in naturally, never mention the judge: {coach}"})
            if not pending_user:
                messages.append({"role": "user", "content": "(Start the conversation in character.)"})
            async for chunk in provider.complete(messages, model=target[2], temperature=0.8, max_tokens=160):
                tutor_line += chunk
                yield _sse("token", {"delta": chunk})
            yield _sse("message_end", {})
            db.add(ChatMessage(session_id=session_id, role="tutor", content=tutor_line))
            db.commit()
        except Exception as e:  # noqa: BLE001 — stream the failure instead of killing the app
            # Full detail stays server-side: the raw exception leaks runtime
            # URLs and internal topology to the client.
            print(f"[verba] tutor generation failed: {e!r}", flush=True)
            yield _sse("error", {"detail": "tutor generation failed — check your model runtime and rescan from Models."})
            yield _sse("done", {"status": "error"})
            return

        if pending_user:
            # The judge must finish and persist even if the client disconnects
            # mid-analysis (page reload, app quit, early Finish): run it as a
            # detached task on its own DB session and only *deliver* the event
            # over this stream.
            async def _judge_and_persist() -> dict[str, Any]:
                try:
                    with Session(engine) as s:
                        diagnosis = await judge_message(s, cs.level, tutor_line, history[-1]["content"], source="tutor")
                        payload = json.dumps(diagnosis)
                        s.add(ChatMessage(session_id=session_id, role="system", content=payload, diagnosis=payload))
                        s.commit()
                    return diagnosis
                except Exception as e:  # noqa: BLE001 — keep the stream alive, log server-side
                    print(f"[verba] judge failed: {e!r}", flush=True)
                    return {"score": 100, "errors": [], "reply_coach": ""}

            judge_task = asyncio.create_task(_judge_and_persist())
            diagnosis = await asyncio.shield(judge_task)
            yield _sse("diagnosis", diagnosis)

        yield _sse("done", {"status": "complete"})

    return StreamingResponse(gen(), media_type="text/event-stream")


class MessageBody(BaseModel):
    text: str


@router.post("/chat/sessions/{session_id}/messages")
def post_message(session_id: str, body: MessageBody, session: Session = Depends(get_session)) -> dict[str, Any]:
    cs = session.get(ChatSession, session_id)
    if cs is None:
        raise HTTPException(status_code=404, detail="session not found")
    if cs.status != "active":
        raise HTTPException(status_code=409, detail="session is closed")
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="empty message")
    session.add(ChatMessage(session_id=session_id, role="user", content=text))
    session.commit()
    return {"queued": True, "stream": f"/api/chat/sessions/{session_id}/stream"}


@router.post("/chat/sessions/{session_id}/finish")
def finish_session(session_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    cs = session.get(ChatSession, session_id)
    if cs is None:
        raise HTTPException(status_code=404, detail="session not found")
    rows = session.exec(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    ).all()
    scores: list[int] = []
    by_category: dict[str, int] = {}
    for m in rows:
        if m.role == "system" and m.diagnosis:
            try:
                d = json.loads(m.content)
            except json.JSONDecodeError:
                continue
            scores.append(int(d.get("score", 100)))
            for e in d.get("errors", []):
                c = str(e.get("category", "grammar"))
                by_category[c] = by_category.get(c, 0) + 1
    cs.status = "done"
    session.add(cs)
    session.commit()
    avg = round(sum(scores) / len(scores)) if scores else 100
    return {"status": "done", "avg_score": avg, "total_errors": sum(by_category.values()), "by_category": by_category}
