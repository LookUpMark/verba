"""Local speech (§9): whisper.cpp STT + OS-native TTS.

The whisper-cli binary is bundled with the app at build time (CI compiles
whisper.cpp and build-sidecar.py drops it next to the server). The acoustic
model (ggml-base.en, ~148 MB) is downloaded once, on explicit user action
from the Models screen — nothing leaves localhost afterwards. TTS uses the
operating system's synthesizer (macOS `say`, Linux `espeak-ng`, Windows SAPI
via PowerShell): no extra downloads, no cloud.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

import httpx

from .grading import _words, word_match_ratio

VOICE_DIR = Path.home() / ".verba" / "voice"
# ggml-base.en q8_0 (~145 MB), pinned to a fixed revision for integrity
# (the original ggerganov/whisper.cpp repo now 401s anonymous downloads).
MODEL_URL = (
    "https://huggingface.co/Pomni/whisper-base.en-ggml-allquants/"
    "resolve/974f5ae273110a1ed561bbd6b564c44376226921/ggml-base.en-q8_0.bin"
)
MODEL_FILE = "ggml-base.en-q8_0.bin"
_TRANScribe_TIMEOUT_S = 300

_lock = threading.Lock()
_state: dict[str, Any] = {"status": "off", "percent": 0, "error": ""}  # off|downloading|ready|error


class VoiceNotReady(RuntimeError):
    pass


def _bundled_binary() -> Path | None:
    name = "whisper-cli.exe" if sys.platform == "win32" else "whisper-cli"
    candidates = [
        Path(getattr(sys, "_MEIPASS", "")) / "voice" / name,  # frozen sidecar
        Path(__file__).resolve().parents[3] / "desktop" / "build" / "whisper-build" / "bin" / name,  # dev tree
    ]
    if sys.platform != "win32":
        with contextlib.suppress(shutil.Error):
            found = shutil.which("whisper-cli")
            if found:
                candidates.append(Path(found))
    return next((c for c in candidates if c.is_file()), None)


def _model_path() -> Path:
    return VOICE_DIR / MODEL_FILE


def state() -> dict[str, Any]:
    binary = _bundled_binary()
    with _lock:
        status = _state["status"]
        if status in ("off", "error") and binary is not None and _model_path().is_file():
            status = "ready"
    return {
        "binary": binary is not None,
        "model": _model_path().is_file(),
        "status": "ready" if status in ("off", "error") and _model_path().is_file() and binary is not None else status,
        "percent": _state["percent"],
        "error": _state["error"],
    }


def enable() -> dict[str, Any]:
    """Start the one-time model download (user-initiated from the Models screen)."""
    if _bundled_binary() is None:
        return {**state(), "error": "no whisper binary in this build"}
    if _model_path().is_file():
        return state()
    with _lock:
        if _state["status"] == "downloading":
            return state()
        _state.update(status="downloading", percent=0, error="")
    threading.Thread(target=_download_worker, daemon=True).start()
    return state()


def _download_worker() -> None:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    part = _model_path().with_suffix(".part")
    try:
        with (
            httpx.Client(timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0), follow_redirects=True) as client,
            client.stream("GET", MODEL_URL) as r,
        ):
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done = 0
            with part.open("wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    with _lock:
                        _state["percent"] = int(100 * done / total) if total else 0
        part.replace(_model_path())
        with _lock:
            _state.update(status="ready", percent=100, error="")
    except Exception as e:  # noqa: BLE001 — surfaced via the state endpoint
        with contextlib.suppress(OSError):
            part.unlink(missing_ok=True)
        with _lock:
            _state.update(status="error", error=str(e))


def transcribe(wav_bytes: bytes) -> str:
    """Run the bundled whisper-cli on a 16 kHz WAV blob, return the transcript."""
    binary, model = _bundled_binary(), _model_path()
    if binary is None or not _model_path().is_file():
        raise VoiceNotReady("voice is not enabled yet — enable it from the Models screen")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes)
        wav = Path(f.name)
    try:
        proc = subprocess.run(  # noqa: S603 — bundled binary, fixed args
            [str(binary), "-m", str(model), "-f", str(wav), "-nt", "-np"],
            capture_output=True,
            text=True,
            timeout=_TRANScribe_TIMEOUT_S,
            check=False,
        )
    finally:
        with contextlib.suppress(OSError):
            wav.unlink()
    if proc.returncode != 0:
        raise RuntimeError(f"whisper-cli failed: {proc.stderr.strip()[:300]}")
    return " ".join(proc.stdout.split()).strip()


def score_pronunciation(target: str, transcript: str) -> dict[str, Any]:
    """Word-level accuracy of the heard transcript against the target (§8)."""
    target_words, heard_words = _words(target), _words(transcript)
    pool = heard_words.copy()
    hit: list[bool] = []
    for w in target_words:
        if w in pool:
            pool.remove(w)
            hit.append(True)
        else:
            hit.append(False)
    return {
        "accuracy": round(100 * word_match_ratio(target, transcript)),
        "missed": [w for w, ok in zip(target_words, hit, strict=False) if not ok],
        "transcript": transcript,
    }


def tts(text: str) -> bytes | None:
    """Synthesize text to WAV bytes with the OS synthesizer, or None if unavailable."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "tts.wav"
        try:
            if sys.platform == "darwin":
                cmd = ["say", "-o", str(out), "--data-format=LEI16@22050", text]
            elif sys.platform == "win32":
                cmd = [
                    "powershell", "-NoProfile", "-Command",
                    "Add-Type -AssemblyName System.Speech; "
                    f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    f"$s.SetOutputToWaveFile('{out}'); $s.Speak('{text.replace(chr(39), '')}'); $s.Dispose()",
                ]
            else:
                cmd = ["espeak-ng", "-w", str(out), text]
            proc = subprocess.run(cmd, capture_output=True, timeout=120, check=False)  # noqa: S603
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0 or not out.is_file():
            return None
        return out.read_bytes()
