from pathlib import Path

import pytest

from sbcx.infra.db import init_db, session_scope
from sbcx.infra.models import PremiumRow

REPO = Path(__file__).resolve().parents[3]
PDFS = REPO / "data/raw/sbc_pdfs"
PUF = REPO / "data/raw/puf/plan-attributes-puf.csv"
IDS = ["10091OR0780001-01", "11718TX0140020-01"]
needs = pytest.mark.skipif(
    not (PUF.exists() and all((PDFS / f"{i}.pdf").exists() for i in IDS)), reason="corpus missing"
)


@needs
def test_ingest_search_facets_premiums(client):
    from sbcx.services.catalog import ingest

    stats = ingest(PDFS, PUF, workers=2, only=IDS)
    assert stats["ok"] == 2 and stats["failed"] == 0

    page = client.get("/api/v1/catalog/plans", params={"state": "TX"}).json()
    assert page["total"] == 1
    plan = page["items"][0]
    assert plan["plan_id"] == "11718TX0140020-01" and plan["document_id"]
    assert plan["metal"] and plan["deductible_individual"] is not None

    doc = client.get(f"/api/v1/documents/{plan['document_id']}").json()
    assert doc["status"] == "ready" and doc["source"] == "catalog"
    assert all(d["id"] != plan["document_id"] for d in client.get("/api/v1/documents").json()["items"])

    f = client.get("/api/v1/catalog/facets").json()
    assert {"value": "TX", "count": 1} in f["state"] and f["premiums_loaded"] is False

    init_db()
    with session_scope() as s:
        s.add(
            PremiumRow(
                plan_key="11718TX0140020",
                state="TX",
                rating_area="Rating Area 3",
                age="40",
                monthly_premium=512.3,
            )
        )
    q = client.get("/api/v1/catalog/plans/11718TX0140020-01/premiums", params={"age": "40"}).json()
    assert q["items"][0]["monthly_premium"] == 512.3

    assert client.get("/api/v1/catalog/plans", params={"q": "zzzz"}).json()["total"] == 0
    assert client.get("/api/v1/catalog/plans/nope").status_code == 404
    assert client.get("/api/v1/catalog/plans", params={"limit": 500}).status_code == 422
