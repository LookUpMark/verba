"""Voice endpoints: local STT (whisper.cpp) and OS-native TTS (§9)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel

from ..services import voice

router = APIRouter()


@router.get("/voice/state")
def voice_state() -> dict[str, Any]:
    return voice.state()


@router.post("/voice/enable")
def voice_enable() -> dict[str, Any]:
    out = voice.enable()
    if out.get("error") == "no whisper binary in this build":
        raise HTTPException(status_code=409, detail=out["error"])
    return out


@router.post("/voice/transcribe")
async def transcribe(request: Request) -> dict[str, Any]:
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=422, detail="empty audio body")
    try:
        text = await run_in_threadpool(voice.transcribe, audio)
    except voice.VoiceNotReady as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"text": text}


class TtsBody(BaseModel):
    text: str


@router.post("/voice/tts")
async def tts(body: TtsBody) -> Response:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="empty text")
    wav = await run_in_threadpool(voice.tts, text[:1000])
    if wav is None:
        raise HTTPException(status_code=503, detail="no OS speech synthesizer available")
    return Response(content=wav, media_type="audio/wav")
