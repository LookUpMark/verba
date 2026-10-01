"""Contract tests for the deterministic judge pre-pass (§7.3)."""

from __future__ import annotations

from verba.pipelines.judge import _merge, _norm_error, _to_int, final_score
from verba.pipelines.rules import rules_scan


def test_rules_catch_planted_errors():
    cats = {(e["wrong"], e["right"]) for e in rules_scan("I am agree with you, and I have 25 years.")}
    assert ("I am agree", "I agree") in cats
    assert ("I have … years", "I am … years old") in cats


def test_a_vowel_rule_respects_consonant_sounds():
    # Audit ATT-8: "a university" / "a European" are correct English.
    wrongs = {e["wrong"] for e in rules_scan("a university, a European car, a one-time fee")}
    assert "a + vowel…" not in wrongs
    wrongs = {e["wrong"] for e in rules_scan("a email, a hour")}
    assert "a + vowel…" in wrongs


def test_score_floor_survives_the_deterministic_veto():
    # Audit ATT-1: with many deterministic findings the veto must not go
    # below the 40 floor.
    assert final_score(100, 10) == 40
    assert final_score(96, 5) == 40
    assert final_score(80, 3) == 80
    assert final_score("not a number", 0) == 100  # ATT-10: degraded field, not a crash
    assert final_score(None, 0) == 100


def test_to_int_is_defensive():
    assert _to_int("42", 0) == 42
    assert _to_int("ottanta", 7) == 7
    assert _to_int(None, 7) == 7
    assert _to_int([], 7) == 7


def test_norm_error_validates_and_defaults():
    good = _norm_error({"category": "TENSE", "wrong": "w", "right": "r", "explanation": "e", "severity": 9})
    assert good is not None and good["category"] == "tense" and good["severity"] == 3
    bad = _norm_error({"category": "grammar", "wrong": "", "right": "r", "explanation": "e"})
    assert bad is None


def test_merge_dedups_on_wrong_case_insensitively():
    pre = [{"category": "grammar", "wrong": "I am agree", "right": "I agree", "explanation": "x", "severity": 2}]
    llm = [{"category": "grammar", "wrong": "i am agree", "right": "I agree", "explanation": "y", "severity": 1}]
    merged = _merge(pre, llm)
    assert len(merged) == 1 and merged[0]["explanation"] == "x"
