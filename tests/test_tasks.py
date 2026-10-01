"""Contract tests for the task engine's validation and ordering."""

from __future__ import annotations

from verba.pipelines.tasks import (
    TASK_KINDS,
    _kind_rank,
    tasks_schema_for,
    validate_payload,
)


def test_validate_payload_accepts_canonical_shapes():
    assert validate_payload("mc", {"prompt": "p", "choices": ["a", "b", "c"], "answer": 1, "why": "w"}) is not None
    assert validate_payload("order", {"prompt": "p", "words": ["a", "b", "c"], "why": "w"}) is not None


def test_validate_payload_rejects_empty_targets():
    # Audit ATT-7: empty text fields must not reach grading.
    assert validate_payload("speaking", {"say": ""}) is None
    assert validate_payload("speaking", {"say": "   "}) is None
    assert validate_payload("translate", {"prompt": "p", "accepted": [""], "why": "w"}) is None
    assert validate_payload("listening", {"say": "x", "accepted": [], "why": "w"}) is None


def test_validate_payload_rejects_out_of_range_answer():
    assert validate_payload("mc", {"prompt": "p", "choices": ["a", "b"], "answer": 5, "why": "w"}) is None


def test_kind_rank_is_canonical_order():
    # Audit ATT-2: Task.id is a random UUID — ordering must come from kinds.
    ranks = [_kind_rank(k) for k in TASK_KINDS]
    assert ranks == sorted(ranks)
    assert _kind_rank("unknown") == len(TASK_KINDS)


def test_tasks_schema_is_sized_to_the_requested_subset():
    schema = tasks_schema_for(["mc", "gap"])
    arr = schema["properties"]["tasks"]
    assert arr["minItems"] == 2 and arr["maxItems"] == 2
    assert schema["properties"]["tasks"]["items"]["properties"]["kind"]["enum"] == ["mc", "gap"]
