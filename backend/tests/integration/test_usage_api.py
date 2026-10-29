"""POST /usage/interpret (v2.1 T4.3, T4.4): grounded events, one retry, clear failures, nothing stored."""

import logging

import pytest

from sbcx.config import get_settings
from sbcx.infra.db import session_scope
from sbcx.infra.llm.fake import FakeLLMClient
from sbcx.infra.models import LLMCallRow
from sbcx.services import usage

URL = "/api/v1/usage/interpret"
TEXT = "I'll see a specialist 4 times this year, and take a generic pill monthly. Dental cleanings too."
GOOD = {
    "events": [
        {"event": "specialist_visit", "count": 4, "member": 0, "quote": "specialist 4 times", "basis": "4"},
        {
            "event": "generic_drug_fill",
            "count": 12,
            "member": 0,
            "quote": "generic pill monthly",
            "basis": "monthly",
        },
    ],
    "unmodeled": [{"quote": "Dental cleanings", "reason": "adult dental isn't in the catalog"}],
}
BAD = {
    "events": [
        {"event": "specialist_visit", "count": 52, "member": 0, "quote": "weekly specialist", "basis": "x"}
    ],
    "unmodeled": [],
}


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "intake_enabled", True)


def script(monkeypatch, *answers):
    fake = FakeLLMClient({"usage_intake": list(answers)})
    monkeypatch.setattr(usage, "get_llm", lambda: fake)
    return fake


def test_disabled_by_default(client):
    assert client.post(URL, json={"text": TEXT}).status_code == 404
    assert client.get("/api/v1/health").json()["intake_available"] is False


def test_interpret(client, enabled, monkeypatch):
    fake = script(monkeypatch, GOOD)
    r = client.post(URL, json={"text": TEXT})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(e["event"], e["count"]) for e in body["events"]] == [
        ("specialist_visit", 4),
        ("generic_drug_fill", 12),
    ]
    assert body["unmodeled"][0]["quote"] == "Dental cleanings"
    call = fake.calls[0]
    assert call["sensitive"] is True and call["task"] == "usage_intake"
    assert "<description>\n" + TEXT in call["user"] and "specialist_visit" in call["system"]
    assert client.get("/api/v1/health").json()["intake_available"] is True


def test_retry_with_violations_then_success(client, enabled, monkeypatch):
    fake = script(monkeypatch, BAD, GOOD)
    assert client.post(URL, json={"text": TEXT}).status_code == 200
    assert "broke the rules" in fake.calls[1]["user"] and "not in the description" in fake.calls[1]["user"]


def test_invalid_twice_is_422(client, enabled, monkeypatch):
    script(monkeypatch, BAD, BAD)
    r = client.post(URL, json={"text": TEXT})
    assert r.status_code == 422 and r.json()["error"]["code"] == "E_INTAKE_INVALID"


def test_no_llm_is_503(client, enabled, monkeypatch):
    monkeypatch.setattr(usage, "get_llm", lambda: None)
    r = client.post(URL, json={"text": TEXT})
    assert r.status_code == 503 and r.json()["error"]["code"] == "E_LLM_UNAVAILABLE"


def test_llm_error_is_503(client, enabled, monkeypatch):
    from sbcx.infra.llm import LLMError

    script(monkeypatch, LLMError("down"))
    assert client.post(URL, json={"text": TEXT}).status_code == 503


def test_family_members(client, enabled, monkeypatch):
    text = "My daughter needs 6 physical therapy sessions."
    answer = {
        "events": [
            {
                "event": "pt_visit",
                "count": 6,
                "member": 1,
                "quote": "6 physical therapy sessions",
                "basis": "6",
            }
        ],
        "unmodeled": [],
    }
    fake = script(monkeypatch, answer)
    r = client.post(
        URL, json={"text": text, "coverage_tier": "family", "members": ["you (40)", "daughter (8)"]}
    )
    assert r.status_code == 200 and r.json()["events"][0]["member"] == 1
    assert "1: daughter (8)" in fake.calls[0]["system"]
    # individual coverage has one member, so member 1 is rejected (and the retry gets the same answer)
    script(monkeypatch, answer, answer)
    assert client.post(URL, json={"text": text}).status_code == 422


@pytest.mark.parametrize("body", [{"text": ""}, {"text": "x" * 1001}, {"text": "ok", "members": ["m"] * 11}])
def test_input_limits(client, enabled, body):
    assert client.post(URL, json=body).status_code == 422


def test_description_is_not_logged_or_stored(client, enabled, monkeypatch, caplog):
    """R-INT-4 / R-PRV-6."""
    caplog.set_level(logging.DEBUG)
    script(monkeypatch, GOOD)
    assert client.post(URL, json={"text": TEXT}).status_code == 200
    logged = "\n".join(r.getMessage() + str(getattr(r, "fields", "")) for r in caplog.records)
    assert "specialist 4 times" not in logged and "Dental" not in logged
    with session_scope() as s:
        rows = s.query(LLMCallRow).all()
    assert all("specialist" not in (r.outcome or "") for r in rows)


def test_default_fake_responder(client, enabled):
    """SBCX_LLM_MODE=fake (tests, E2E) has a deterministic intake answer."""
    r = client.post(
        URL, json={"text": "I expect 3 specialist visits and I'm having a baby. Dental cleanings."}
    )
    assert r.status_code == 200, r.text
    assert {e["event"] for e in r.json()["events"]} == {"specialist_visit", "childbirth"}
