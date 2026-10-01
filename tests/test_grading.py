"""Contract tests for the deterministic task grading (§8)."""

from __future__ import annotations

import json

from verba.services.grading import grade_task, word_match_ratio


def test_mc_matches_by_letter_index():
    payload = json.dumps({"prompt": "p", "choices": ["is", "are"], "answer": 0, "why": "w"})
    ok, correct = grade_task("mc", payload, "a")
    assert ok is True
    assert correct == "is"
    ok, _ = grade_task("mc", payload, "b")
    assert ok is False


def test_translate_accepts_any_accepted_form():
    payload = json.dumps({"prompt": "p", "accepted": ["nice to meet you"], "why": "w"})
    ok, _ = grade_task("translate", payload, "  Nice to meet you! ")
    assert ok is True
    ok, _ = grade_task("translate", payload, "hello")
    assert ok is False


def test_order_requires_exact_sequence():
    payload = json.dumps({"prompt": "p", "words": ["This", "is", "my", "friend"], "why": "w"})
    ok, _ = grade_task("order", payload, "This is my friend")
    assert ok is True
    ok, _ = grade_task("order", payload, "my This friend is")
    assert ok is False


def test_speaking_word_match_threshold():
    payload = json.dumps({"say": "Nice to meet you today"})
    ok, _ = grade_task("speaking", payload, "Nice to meet you today")
    assert ok is True
    ok, _ = grade_task("speaking", payload, "banana banana")
    assert ok is False


def test_empty_target_grades_incorrect_not_correct():
    # Audit ATT-7: an empty model-provided target must not accept anything.
    assert word_match_ratio("", "anything at all") == 0.0
    payload = json.dumps({"say": ""})
    ok, _ = grade_task("speaking", payload, "whatever")
    assert ok is False
