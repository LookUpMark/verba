"""QA round 2026-10-12 — unit tests for the coverage gaps found by qa-full.

Covers the untested branches of grading (listening / unknown kind), the srs
"hard" grade, the lowercase-"i" pre-pass rule and score_pronunciation.
"""

from __future__ import annotations

import json

from verba.pipelines.judge import _merge, final_score
from verba.pipelines.rules import rules_scan
from verba.services.grading import grade_task
from verba.services.srs import RETIRE_AT, schedule
from verba.services.voice import score_pronunciation


def _card(stability: float = 2.0, difficulty: float = 5.0):
    from verba.models import SrsCard

    return SrsCard(front="front", back="back", stability=stability, difficulty=difficulty)


class TestGradingGaps:
    def test_listening_accepts_any_accepted_form(self):
        payload = json.dumps({"accepted": ["Where is the gate?", "where's the gate"], "say": "Where is the gate?"})
        ok, correct = grade_task("listening", payload, "Where is the gate?")
        assert ok is True and correct == "Where is the gate?"

    def test_listening_rejects_wrong_answer(self):
        payload = json.dumps({"accepted": ["Where is the gate?"], "say": "Where is the gate?"})
        ok, correct = grade_task("listening", payload, "Where is the gateman")
        assert ok is False and correct == "Where is the gate?"

    def test_unknown_kind_is_incorrect_with_empty_correct_answer(self):
        assert grade_task("cloze", json.dumps({"x": 1}), "anything") == (False, "")


class TestSrsHardGrade:
    def test_hard_grows_stability_with_floor_and_is_not_immediate(self):
        from datetime import datetime, timedelta, timezone

        card = _card(stability=0.2)
        before = datetime.now(timezone.utc)
        schedule(card, "hard")
        assert card.stability == 0.5  # max(0.5, 0.2*1.2) — the floor holds
        assert card.last_grade == "hard"
        assert not card.retired
        due = datetime.fromisoformat(card.due_at)
        assert due - before >= timedelta(hours=8)  # max(8h, day*stability*0.8)

    def test_hard_from_high_stability_never_retires_below_threshold(self):
        card = _card(stability=15.0)
        schedule(card, "hard")
        assert card.stability == 15.0 * 1.2
        assert card.retired is (card.stability >= RETIRE_AT)


class TestRulesStandaloneI:
    def test_lowercase_standalone_i_is_flagged(self):
        errors = rules_scan("and then i went home")
        kinds = {(e["category"], e["wrong"]) for e in errors}
        assert ("mechanics", "lowercase i") in kinds

    def test_capitalized_i_is_not_flagged(self):
        errors = rules_scan("And then I went home")
        assert not any(e["wrong"] == "lowercase i" for e in errors)


class TestFinalScoreEdges:
    def test_garbage_score_falls_back_to_100_then_clamps(self):
        assert final_score(None, 0) == 100
        assert final_score("not-a-number", 0) == 100
        assert final_score(-5, 0) == 40
        assert final_score(500, 0) == 100

    def test_veto_can_pull_below_the_llm_floor_but_never_under_40(self):
        assert final_score(100, 5) == 40
        assert final_score(96, 1) == 88


class TestMergeEdgeCases:
    def test_merge_caps_at_eight_errors(self):
        llm = [{"wrong": f"e{i}", "right": "r", "explanation": "x", "category": "grammar", "severity": 2} for i in range(12)]
        assert len(_merge([], llm)) == 8

    def test_merge_prefers_the_pre_pass_finding(self):
        pre = [{"wrong": "I am agree", "right": "I agree", "explanation": "pre-pass", "category": "grammar", "severity": 2}]
        llm = [{"wrong": "i am agree", "right": "LLM version", "explanation": "x", "category": "grammar", "severity": 3}]
        merged = _merge(pre, llm)
        assert len(merged) == 1 and merged[0]["explanation"] == "pre-pass"


class TestScorePronunciation:
    def test_perfect_transcript_is_100(self):
        result = score_pronunciation("Where is the gate?", "Where is the gate")
        assert result["accuracy"] == 100 and result["missed"] == []

    def test_missed_words_are_listed_in_order(self):
        result = score_pronunciation("I would like a coffee", "I like a coffee")
        assert result["missed"] == ["would"]
        assert result["accuracy"] == 80

    def test_duplicate_heard_words_do_not_inflate_accuracy(self):
        # "the the the" matches only one "the" of the target
        result = score_pronunciation("the cat", "the the the")
        assert result["accuracy"] == 50 and result["missed"] == ["cat"]

    def test_empty_transcript_is_zero_not_a_crash(self):
        result = score_pronunciation("Where is the gate?", "")
        assert result["accuracy"] == 0 and len(result["missed"]) == 4
