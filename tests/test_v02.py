"""Contract tests for v0.2: schema validation, reply_coach, runtime setup, voice."""

from __future__ import annotations

import json

from verba.db import engine
from verba.models import ChatMessage
from verba.pipelines import validate_against_schema
from verba.pipelines.tasks import validate_payload
from verba.services.voice import VoiceNotReady, score_pronunciation, state as voice_state, transcribe
from sqlmodel import Session


def test_validate_against_schema_accepts_and_rejects():
    schema = {
        "type": "object",
        "properties": {"score": {"type": "integer", "minimum": 0, "maximum": 100}},
        "required": ["score"],
    }
    assert validate_against_schema({"score": 80}, schema) is None
    problem = validate_against_schema({"score": "eighty"}, schema)
    assert problem is not None and "score" in problem
    problem = validate_against_schema({"score": 500}, schema)
    assert problem is not None


def test_task_payload_now_schema_validated():
    # answer must be an integer index — a string "0" (a classic small-model
    # slip) now fails the schema instead of reaching grading.
    assert validate_payload("mc", {"prompt": "p", "choices": ["a", "b", "c"], "answer": "0", "why": "w"}) is None
    assert validate_payload("mc", {"prompt": "p", "choices": ["a", "b", "c"], "answer": 1, "why": "w"}) is not None


def test_voice_state_shape():
    st = voice_state()
    assert set(st) >= {"binary", "model", "status", "percent", "error"}
    assert st["status"] in ("off", "downloading", "ready", "error")


def test_transcribe_never_silently_succeeds_on_garbage():
    # Without binary+model it raises VoiceNotReady; with a real local setup
    # garbage input yields an empty transcript at best. Never real speech.
    try:
        text = transcribe(b"not-a-wav")
    except (VoiceNotReady, RuntimeError):
        return
    assert text == ""


def test_pronunciation_scoring():
    out = score_pronunciation("Nice to meet you today", "nice to meet you")
    assert out["accuracy"] == 80  # 4 of 5 target words heard
    assert out["missed"] == ["today"]
    assert out["transcript"] == "nice to meet you"


def test_last_coach_reads_the_newest_diagnosis(client):
    from verba.api.routes_chat import _last_coach

    with Session(engine) as s:
        s.add(ChatMessage(session_id="coach-test", role="system", content=json.dumps({"reply_coach": "use 'I agree'", "score": 40})))
        s.add(ChatMessage(session_id="coach-test", role="system", content=json.dumps({"reply_coach": "", "score": 100})))
        s.commit()
    # The newest row has an empty coach: the helper skips it and finds the
    # previous non-empty one.
    assert _last_coach(s, "coach-test") == "use 'I agree'"


def test_runtime_setup_state(client):
    r = client.get("/api/runtime/setup")
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {"omlx", "ollama", "lmstudio"}
    for rt in data.values():
        assert set(rt) >= {"id", "name", "endpoint", "server_up", "hint"}


def test_pull_rejected_without_ollama(client):
    # CI and this machine have no Ollama CLI: the endpoint must refuse cleanly.
    r = client.post("/api/runtime/ollama/pull", json={"model": "qwen3:8b"})
    assert r.status_code == 409


def test_voice_endpoints_guard(client):
    st = client.get("/api/voice/state")
    assert st.status_code == 200
    empty = client.post("/api/voice/transcribe", content=b"")
    assert empty.status_code == 422
