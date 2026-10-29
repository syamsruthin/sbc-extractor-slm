"""Privacy controls (v2.1 M3): deleting saved comparisons, retention, and logs without personal data."""

import json
import logging
from datetime import UTC, datetime, timedelta

from sbcx.infra.db import session_scope
from sbcx.infra.models import ComparisonRow, LLMCallRow
from sbcx.logs import JsonFormatter
from sbcx.services.comparison import purge_older_than
from tests.fixtures import f1, seed_f1

SECRET_EVENT = "therapy_visit"  # an event type that says something about the user's health


def body(**kw):
    return {
        **f1()["request"],
        "custom_scenario": {
            "id": "custom",
            "label": "Mine",
            "events": [{"event": SECRET_EVENT, "count": 26}],
        },
        "profile": {"ages": [47, 12], "rating_areas": {"TX": "Rating Area 3"}},
        **kw,
    }


def test_delete_one_and_all(client):
    seed_f1()
    ids = [client.post("/api/v1/comparisons", json=body(explain=False)).json()["id"] for _ in range(3)]
    listed = client.get("/api/v1/comparisons").json()
    assert {i["id"] for i in listed} == set(ids)
    assert listed[0]["scenario_labels"] == ["Low use", "Moderate use", "High use", "Mine"]

    assert client.delete(f"/api/v1/comparisons/{ids[0]}").status_code == 204
    assert client.get(f"/api/v1/comparisons/{ids[0]}").status_code == 404
    r = client.delete(f"/api/v1/comparisons/{ids[0]}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "E_NOT_FOUND"

    assert client.delete("/api/v1/comparisons").status_code == 204
    assert client.get("/api/v1/comparisons").json() == []


def test_retention_purges_old_comparisons(client):
    seed_f1()
    keep = client.post("/api/v1/comparisons", json=body(explain=False)).json()["id"]
    old = client.post("/api/v1/comparisons", json=body(explain=False)).json()["id"]
    with session_scope() as s:
        s.get(ComparisonRow, old).created_at = datetime.now(UTC) - timedelta(days=31)
    assert purge_older_than(30) == 1
    assert [i["id"] for i in client.get("/api/v1/comparisons").json()] == [keep]


def test_logs_hold_no_request_bodies_or_llm_text(client, caplog):
    """R-PRV-6: app logs and the llm_calls table record what happened, never what the user entered."""
    seed_f1()
    caplog.set_level(logging.DEBUG)
    r = client.post("/api/v1/comparisons", json=body(explain=True))  # fake LLM writes the explanation
    assert r.status_code == 201
    explanation = client.get(f"/api/v1/comparisons/{r.json()['id']}").json()["explanation"]["content"]
    lines = [JsonFormatter().format(rec) for rec in caplog.records]
    text = "\n".join(lines)
    assert lines, "expected request logs"
    for secret in (SECRET_EVENT, '"ages"', "Rating Area 3", explanation["headline"]):
        assert secret not in text, secret
    with session_scope() as s:
        calls = [
            json.dumps({c.key: getattr(row, c.key) for c in LLMCallRow.__table__.columns}, default=str)
            for row in s.query(LLMCallRow)
        ]
    assert not any(SECRET_EVENT in c or explanation["headline"] in c for c in calls)
