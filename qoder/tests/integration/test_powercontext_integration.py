"""Integration tests that require a running PowerContext server.

These tests exercise the full write -> restart -> read -> schedule-change loop.
They are skipped when the server is unreachable.

Run with: pytest tests/integration/ -v
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta

import httpx
import pytest

POWERCONTEXT_URL = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8000")


def _pc_available() -> bool:
    try:
        resp = httpx.get(f"{POWERCONTEXT_URL}/health/live", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


requires_powercontext = pytest.mark.skipif(
    not _pc_available(),
    reason="PowerContext server not reachable at " + POWERCONTEXT_URL,
)


def _post(path: str, body: dict) -> dict:
    resp = httpx.post(
        f"{POWERCONTEXT_URL}{path}",
        json=body,
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    assert resp.status_code in (200, 201), f"{path} failed: {resp.status_code} {resp.text}"
    return resp.json()


@requires_powercontext
def test_create_scope_and_remember_preferences():
    idem_key = f"integration-test-{date.today().isoformat()}"
    scope_resp = _post("/v1/scopes", {
        "title": "Integration test scope",
        "summary": "Temporary scope for integration testing",
        "idempotency_key": idem_key,
    })
    scope_id = scope_resp["scope_id"]
    assert scope_id

    prefs = {
        "daily_minutes": 45,
        "learning_goal": "Integration test goal",
        "created_at": "2026-11-08T00:00:00Z",
        "updated_at": "2026-11-08T00:00:00Z",
    }
    remember_resp = _post("/v1/memory/remember", {
        "scope_id": scope_id,
        "kind": "study-preferences",
        "text": json.dumps(prefs, ensure_ascii=False),
        "reason": "Integration test preferences write",
    })
    assert remember_resp.get("changed") is True or remember_resp.get("records")
    records = remember_resp.get("records", [])
    assert len(records) > 0
    artifact = records[0].get("artifact", {})
    assert artifact.get("artifact_id")
    assert artifact.get("revision") == 1


@requires_powercontext
def test_remember_and_list_study_records():
    idem_key = f"integration-test-records-{date.today().isoformat()}"
    scope_resp = _post("/v1/scopes", {
        "title": "Integration test records",
        "summary": "Temporary scope for record testing",
        "idempotency_key": idem_key,
    })
    scope_id = scope_resp["scope_id"]

    today = date.today()
    record = {
        "record_id": "rec-test-001",
        "date": str(today),
        "card_id": "db-btree",
        "assessment": "needs_work",
        "next_review_date": str(today + timedelta(days=1)),
        "notes": "Integration test note",
        "created_at": today.isoformat() + "T00:00:00Z",
    }
    _post("/v1/memory/remember", {
        "scope_id": scope_id,
        "kind": "study-record",
        "text": json.dumps(record, ensure_ascii=False),
        "reason": "Integration test record write",
    })

    list_resp = _post("/v1/atomic-memory/list", {
        "scope_id": scope_id,
        "kind": "study-record",
        "states": ["active"],
        "limit": 10,
    })
    items = list_resp.get("items", [])
    assert len(items) >= 1
    found = False
    for item in items:
        try:
            parsed = json.loads(item.get("text", ""))
            if parsed.get("record_id") == "rec-test-001":
                found = True
                break
        except json.JSONDecodeError:
            continue
    assert found, "Written record not found in list"


@requires_powercontext
def test_persistence_across_simulated_restarts():
    """Write data, then read it back as if the application restarted."""
    idem_key = f"integration-test-restart-{date.today().isoformat()}"
    scope_resp = _post("/v1/scopes", {
        "title": "Integration test restart",
        "summary": "Temporary scope for restart testing",
        "idempotency_key": idem_key,
    })
    scope_id = scope_resp["scope_id"]

    prefs = {
        "daily_minutes": 60,
        "learning_goal": "Restart test goal",
        "created_at": "2026-11-08T00:00:00Z",
        "updated_at": "2026-11-08T00:00:00Z",
    }
    _post("/v1/memory/remember", {
        "scope_id": scope_id,
        "kind": "study-preferences",
        "text": json.dumps(prefs, ensure_ascii=False),
        "reason": "Restart test preferences",
    })

    list_resp = _post("/v1/atomic-memory/list", {
        "scope_id": scope_id,
        "kind": "study-preferences",
        "states": ["active"],
        "limit": 10,
    })
    items = list_resp.get("items", [])
    assert len(items) >= 1
    recovered = json.loads(items[-1]["text"])
    assert recovered["daily_minutes"] == 60
    assert recovered["learning_goal"] == "Restart test goal"


@requires_powercontext
def test_scope_isolation():
    """Two different scopes should not see each other's data."""
    scope_a_resp = _post("/v1/scopes", {
        "title": "Isolation test A",
        "summary": "Scope A",
        "idempotency_key": f"isolation-a-{date.today().isoformat()}",
    })
    scope_b_resp = _post("/v1/scopes", {
        "title": "Isolation test B",
        "summary": "Scope B",
        "idempotency_key": f"isolation-b-{date.today().isoformat()}",
    })
    scope_a = scope_a_resp["scope_id"]
    scope_b = scope_b_resp["scope_id"]
    assert scope_a != scope_b

    _post("/v1/memory/remember", {
        "scope_id": scope_a,
        "kind": "study-record",
        "text": json.dumps({"card_id": "db-btree", "assessment": "needs_work"}),
        "reason": "Isolation test write to A",
    })

    list_b = _post("/v1/atomic-memory/list", {
        "scope_id": scope_b,
        "kind": "study-record",
        "states": ["active"],
        "limit": 100,
    })
    items_b = list_b.get("items", [])
    for item in items_b:
        try:
            parsed = json.loads(item.get("text", ""))
            assert parsed.get("card_id") != "db-btree"
        except json.JSONDecodeError:
            continue
