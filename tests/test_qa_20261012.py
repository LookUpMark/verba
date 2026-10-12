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

class TestQaFixRegressions:
    """Regression tests for the bugs found by the 2026-10-12 QA round."""

    def test_empty_answer_never_grades_mc_gap_correct(self):
        payload = json.dumps({"choices": ["right", "b", "c", "d"], "answer": 0})
        assert grade_task("mc", payload, "") == (False, "right")
        assert grade_task("mc", payload, "   ") == (False, "right")
        gap = json.dumps({"choices": ["a", "right", "c", "d"], "answer": 1})
        assert grade_task("gap", gap, "") == (False, "right")
        # whitespace-only noise is not a letter either
        assert grade_task("mc", payload, "ab1") == (False, "right")

    def test_placement_unlocks_in_curriculum_order(self, client):
        # A2 placement: exactly the 3 A1 missions become done, current = first A2 mission
        r = client.post("/api/onboarding/placement", json={"correct": 3, "questions": 5})
        assert r.status_code == 200 and r.json()["level"] == "A2"
        tree = client.get("/api/path").json()["tree"]
        flat = [m for lvl in tree for u in lvl["units"] for m in u["missions"]]
        done = [m["id"] for m in flat if m["state"] == "done"]
        current = next(m["id"] for m in flat if m["state"] == "current")
        assert done == [m["id"] for m in flat[:3]]  # the whole first level
        assert current == flat[3]["id"]  # the first mission of the placed level
        assert tree[1]["cefr"] == "A2"

    def test_b2_placement_lands_on_first_b2_mission(self, client):
        r = client.post("/api/onboarding/placement", json={"correct": 5, "questions": 5})
        assert r.json()["level"] == "B2"
        tree = client.get("/api/path").json()["tree"]
        flat = [m for lvl in tree for u in lvl["units"] for m in u["missions"]]
        done_n = sum(1 for m in flat if m["state"] == "done")
        current = next(m for m in flat if m["state"] == "current")
        assert done_n == 9  # 3+3+3 of the preceding levels
        b2_first = next(m for lvl in tree if lvl["cefr"] == "B2" for u in lvl["units"] for m in u["missions"])
        assert current["id"] == b2_first["id"]

    def test_complete_without_attempts_is_refused(self, client):
        tree = client.get("/api/path").json()["tree"]
        some_mission = next(m for lvl in tree for u in lvl["units"] for m in u["missions"])["id"]
        r = client.post(f"/api/missions/{some_mission}/complete", json={"correct": 999, "total": 1000})
        assert r.status_code == 400
        assert "no attempts" in r.json()["detail"]


class TestQaUiNav:
    def test_bottombar_has_the_same_screens_as_the_sidebar(self):
        import pathlib
        import re

        html = pathlib.Path(__file__).resolve().parents[1].joinpath("index.html").read_text(encoding="utf-8")
        sidebar = re.search(r'<nav class="nav"(.*?)</nav>', html, re.S).group(1)
        bottombar = re.search(r'<nav class="bottombar"(.*?)</nav>', html, re.S).group(1)
        assert set(re.findall(r'data-nav="(\w+)"', sidebar)) == set(re.findall(r'data-nav="(\w+)"', bottombar))
