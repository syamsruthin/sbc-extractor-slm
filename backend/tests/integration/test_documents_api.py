"""Upload -> background extraction -> read. Uses a real SBC PDF from the local corpus (skipped when
data/raw is not present, since PDFs aren't in git)."""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PDF = REPO / "data/raw/sbc_pdfs/10091OR0780001-01.pdf"
needs_pdf = pytest.mark.skipif(not PDF.exists(), reason="local SBC corpus not available")


@needs_pdf
def test_upload_extract_read_dedupe(client):
    data = PDF.read_bytes()
    r = client.post("/api/v1/documents", files={"file": ("core-gold.pdf", data, "application/pdf")})
    assert r.status_code == 202, r.text
    doc_id = r.json()["id"]

    # TestClient runs background tasks before returning, so extraction is done
    d = client.get(f"/api/v1/documents/{doc_id}").json()
    assert d["status"] == "ready", d
    b = d["benefits"]["benefits"]
    assert b["plan_name"] == "Core Gold 1500"
    assert b["deductible"]["in_network"] == {"individual": 1500.0, "family": 3000.0}
    assert b["services"]["specialist_visit"]["in_network"]["copay"] == 50.0
    assert d["summaries_status"] in ("ready", "skipped")

    from sbcx.domain.extract.run import extract_pdf

    direct, _, _ = extract_pdf(PDF)
    assert direct.benefits.model_dump(mode="json") == b

    p = client.get(
        f"/api/v1/documents/{doc_id}/provenance",
        params={"path": "services.specialist_visit.in_network.copay"},
    ).json()
    assert p["value"] == 50.0 and p["meta"]["page"] == 2 and "$50" in p["meta"]["raw_text"]

    again = client.post("/api/v1/documents", files={"file": ("copy.pdf", data, "application/pdf")})
    assert again.status_code == 200 and again.json()["id"] == doc_id

    items = client.get("/api/v1/documents").json()["items"]
    assert any(i["id"] == doc_id for i in items)
    assert client.get(f"/api/v1/documents/{doc_id}/pdf").content[:4] == b"%PDF"


def test_rejects_non_pdf(client):
    r = client.post("/api/v1/documents", files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "E_NOT_PDF"


def test_missing_file_is_validation_error(client):
    r = client.post("/api/v1/documents")
    assert r.status_code == 422 and r.json()["error"]["code"] == "E_VALIDATION"


def test_unknown_document(client):
    r = client.get("/api/v1/documents/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "E_NOT_FOUND"


@needs_pdf
def test_bad_provenance_path(client):
    doc_id = client.post(
        "/api/v1/documents", files={"file": ("a.pdf", PDF.read_bytes(), "application/pdf")}
    ).json()["id"]
    r = client.get(f"/api/v1/documents/{doc_id}/provenance", params={"path": "services.nope.copay"})
    assert r.status_code == 404
