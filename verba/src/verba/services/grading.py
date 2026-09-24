"""Deterministic task grading per kind (prototype parity, §8)."""

from __future__ import annotations

import json
import re

CATEGORY_BY_KIND = {
    "mc": "grammar",
    "gap": "grammar",
    "translate": "grammar",
    "order": "word_order",
    "listening": "listening",
    "speaking": "speaking",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[.,!?;:'\"’]", "", s.lower())).strip()


def _words(s: str) -> list[str]:
    return [w for w in _norm(s).split() if w]


def word_match_ratio(target: str, heard: str) -> float:
    t, h = _words(target), _words(heard)
    if not t:
        return 1.0
    pool = h.copy()
    matched = 0
    for w in t:
        if w in pool:
            pool.remove(w)
            matched += 1
    return matched / len(t)


def grade_task(kind: str, payload_json: str, answer: str) -> tuple[bool, str]:
    """Returns (is_correct, correct_answer_text)."""
    payload = json.loads(payload_json)
    if kind in ("mc", "gap"):
        idx = "abcd".find(_norm(answer))
        correct_text = str(payload["choices"][payload["answer"]])
        return idx == payload["answer"], correct_text
    if kind == "translate":
        accepted = [str(a) for a in payload.get("accepted", [])]
        correct_text = payload.get("answerText") or (accepted[0] if accepted else "")
        return _norm(answer) in {_norm(a) for a in accepted}, correct_text
    if kind == "order":
        target = " ".join(str(w) for w in payload["words"])
        return _norm(answer) == _norm(target), target
    if kind == "listening":
        accepted = [str(a) for a in payload["accepted"]]
        return _norm(answer) in {_norm(a) for a in accepted}, payload["say"]
    if kind == "speaking":
        target = str(payload["say"])
        return word_match_ratio(target, answer) >= 0.8, target
    return False, ""
