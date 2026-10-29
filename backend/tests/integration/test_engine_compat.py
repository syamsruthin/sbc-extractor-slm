"""Engine 1.3.0 against stored results and the API (v2.1 T1.1, T1.4)."""

from sbcx.infra.db import session_scope
from sbcx.infra.models import ComparisonRow
from tests.fixtures import f1, seed_f1


def test_stored_engine_120_result_still_loads(client):
    """D8: comparisons stored before engine 1.3.0 are served as stored, without the new fields."""
    fx = f1()
    with session_scope() as s:
        s.add(
            ComparisonRow(
                id="old120",
                request=fx["request"],
                result=fx["result"],
                engine_version="1.2.0",
                explanation_status="ready",
                explanation=fx["explanation"],
            )
        )
    r = client.get("/api/v1/comparisons/old120")
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["engine_version"] == "1.2.0" and res["result_hash"] == fx["result"]["result_hash"]
    spec = next(d for d in res["services"] if d["service_key"] == "specialist_visit")
    assert spec["overall_verdicts"] == {} and spec["cells"]["B"]["est_cost_before_deductible"] is None


def test_new_comparison_has_before_deductible_fields(client):
    seed_f1()
    r = client.post("/api/v1/comparisons", json={**f1()["request"], "explain": False})
    assert r.status_code == 201, r.text
    res = r.json()["result"]
    assert res["engine_version"] == "1.3.0"
    spec = next(d for d in res["services"] if d["service_key"] == "specialist_visit")
    assert spec["overall_verdicts"] == {"B": "depends_on_deductible"}
    assert spec["cells"]["B"]["est_cost_before_deductible"] == {"low": 250.0, "high": 250.0}
