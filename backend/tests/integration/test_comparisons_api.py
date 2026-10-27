from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PDFS = [REPO / "data/raw/sbc_pdfs/10091OR0780001-01.pdf", REPO / "data/raw/sbc_pdfs/13262AR0230010-00.pdf"]
needs = pytest.mark.skipif(not all(p.exists() for p in PDFS), reason="local SBC corpus not available")


def upload(client, p: Path) -> str:
    r = client.post("/api/v1/documents", files={"file": (p.name, p.read_bytes(), "application/pdf")})
    assert r.status_code in (200, 202), r.text
    return r.json()["id"]


@needs
def test_compare_and_explain(client):
    a, b = (upload(client, p) for p in PDFS)
    body = {
        "document_ids": [a, b],
        "inputs": {a: {"monthly_premium": 520}, b: {"monthly_premium": 410}},
        "scenario_ids": ["low", "moderate", "high"],
        "custom_scenario": {
            "id": "custom",
            "label": "My year",
            "events": [{"event": "specialist_visit", "count": 6}],
        },
    }
    r = client.post("/api/v1/comparisons", json=body)
    assert r.status_code == 201, r.text
    c = r.json()
    res = c["result"]
    assert [p["plan_key"] for p in res["plans"]] == ["A", "B"] and res["plans"][0]["is_base"]
    assert res["headline"]["annual_premium"] == {"A": 6240.0, "B": 4920.0}
    assert {s["scenario"]["id"] for s in res["scenarios"]} == {"low", "moderate", "high", "custom"}
    assert len(res["services"]) == 26 and res["result_hash"]

    got = client.get(f"/api/v1/comparisons/{c['id']}").json()
    assert got["explanation_status"] == "ready"  # fake LLM in tests; background task already ran
    exp = got["explanation"]
    assert exp["grounding"]["ok"] and exp["content"]["disclaimer"]

    again = client.post("/api/v1/comparisons", json=body).json()
    assert again["result"]["result_hash"] == res["result_hash"]

    regen = client.post(f"/api/v1/comparisons/{c['id']}/explanation")
    assert regen.status_code == 202
    assert any(i["id"] == c["id"] for i in client.get("/api/v1/comparisons").json())


@needs
def test_compare_errors(client):
    a = upload(client, PDFS[0])
    assert client.post("/api/v1/comparisons", json={"document_ids": [a]}).status_code == 422
    r = client.post("/api/v1/comparisons", json={"document_ids": [a, "missing"]})
    assert r.status_code == 404
    b = upload(client, PDFS[1])
    r = client.post("/api/v1/comparisons", json={"document_ids": [a, b], "scenario_ids": ["nope"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "E_UNKNOWN_SCENARIO"


def test_meta(client):
    s = client.get("/api/v1/meta/scenarios").json()
    assert {p["id"] for p in s["presets"]} >= {"low", "moderate", "high", "baby"} and "mri" in s[
        "event_types"
    ]
    p = client.get("/api/v1/meta/reference-prices").json()
    assert p["prices"]["imaging"] > 0 and p["labels"]["drug:generic"] == "Generic drugs"
    assert "llm" in client.get("/api/v1/meta/usage").json()


@needs
def test_degraded_mode_without_llm(client, monkeypatch):
    """No API key / LLM off: extraction, summaries (templates) and explanation (template) still work."""
    from sbcx.config import get_settings
    from sbcx.infra.llm import reset_llm

    monkeypatch.setenv("SBCX_LLM_MODE", "off")
    get_settings.cache_clear()
    reset_llm()
    try:
        assert client.get("/api/v1/health").json()["llm_configured"] is False
        a, b = (upload(client, p) for p in PDFS)
        doc = client.get(f"/api/v1/documents/{a}").json()
        assert doc["summaries_status"] == "ready"
        assert {s["source"] for s in doc["benefits"]["summaries"]} == {"template"}
        c = client.post("/api/v1/comparisons", json={"document_ids": [a, b]}).json()
        exp = client.get(f"/api/v1/comparisons/{c['id']}").json()["explanation"]
        assert exp["source"] == "template" and exp["grounding"]["ok"]
    finally:
        monkeypatch.delenv("SBCX_LLM_MODE")
        get_settings.cache_clear()
        reset_llm()
