"""Hermetic test setup: env vars must be set before any `verba` import.

No LLM spawn, no real runtime probes, throwaway DB per test session.
"""

from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="verba-tests-")
os.environ["VERBA_DB"] = os.path.join(_TMP, "verba-test.db")
os.environ["VERBA_LLM_SPAWN"] = "0"
os.environ["VERBA_PROBE_TIMEOUT"] = "0.1"
os.environ["VERBA_MLX_ENDPOINT"] = "http://127.0.0.1:9/v1"  # closed port: instant refusal

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from verba.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    # Session-scoped: lifespan (DB init, seed, discovery) runs once.
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c
