"""API smoke tests on the real app stack (lifespan: init_db, seed, discovery).

Also locks in the local-only guard from the audit (attacker-1/attacker-5).
"""

from __future__ import annotations


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_path_seeds_the_full_skeleton(client):
    r = client.get("/api/path")
    assert r.status_code == 200
    data = r.json()
    missions = [m for lev in data["tree"] for u in lev["units"] for m in u["missions"]]
    assert len(missions) == 11
    assert [lev["cefr"] for lev in data["tree"]] == ["A1", "A2", "B1", "B2"]
    assert data["current"] is not None


def test_onboarding_placement_and_goal(client):
    r = client.post("/api/onboarding/placement", json={"correct": 3, "questions": 5})
    assert r.status_code == 200 and r.json()["level"] == "A2"
    r = client.post("/api/onboarding/goal", json={"target": 25})
    assert r.status_code == 200 and r.json()["goal_target"] == 25
    r = client.post("/api/onboarding/goal", json={"target": 1000})
    assert r.json()["goal_target"] == 200  # clamped


def test_review_queue_has_seed_cards_and_grading_schedules(client):
    data = client.get("/api/review/queue").json()
    assert data["count"] >= 10
    card = data["due"][0]
    r = client.post("/api/review/grade", json={"card_id": card["id"], "grade": "good"})
    assert r.status_code == 200 and "due_at" in r.json()
    assert client.post("/api/review/grade", json={"card_id": "nope", "grade": "good"}).status_code == 404


def test_stats_endpoints(client):
    overview = client.get("/api/stats/overview").json()
    assert set(overview) >= {"xp", "streak", "missions_done", "level"}
    daily = client.get("/api/stats/daily?days=14").json()
    assert isinstance(daily, list) and len(daily) == 14
    assert client.get("/api/stats/library").json()["srs_cards"] >= 10


def test_roles_reject_unknown_runtime(client):
    r = client.put("/api/roles", json={"role": "tutor", "runtime": "missing", "model_id": "m"})
    assert r.status_code == 404


def test_unknown_host_is_forbidden(client):
    # Audit attacker-1: a rebound DNS name shows up in the Host header.
    r = client.get("/api/health", headers={"Host": "evil.example.com"})
    assert r.status_code == 403


def test_cross_origin_requests_are_forbidden(client):
    # Audit attacker-1: browsers attach Origin to every cross-origin POST;
    # drive-by shutdown/generation calls must die here.
    assert client.get("/api/health", headers={"Origin": "https://evil.example.com"}).status_code == 403
    assert client.post("/api/shutdown", headers={"Origin": "https://evil.example.com"}).status_code == 403
    assert client.post("/api/shutdown", headers={"Origin": "http://127.0.0.1"}).status_code in (200, 409)


def test_security_headers_are_set(client):
    # Audit dependency-1: the sidecar response is the only CSP surface.
    r = client.get("/api/health")
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp and "connect-src 'self'" in csp
    assert r.headers.get("x-content-type-options") == "nosniff"
