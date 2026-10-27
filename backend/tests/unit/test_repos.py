import pytest
from sqlalchemy.exc import IntegrityError

from sbcx.infra.db import init_db, session_scope
from sbcx.infra.models import DocumentRow, PremiumRow
from sbcx.infra.repos import (
    CatalogRepo,
    ComparisonRepo,
    DocumentRepo,
    PremiumRepo,
    llm_usage,
    record_llm_call,
)


@pytest.fixture(autouse=True)
def db():
    init_db()


def test_document_dedupe_by_sha():
    with session_scope() as s:
        r = DocumentRepo(s).add(DocumentRow(sha256="a" * 64, filename="x.pdf"))
        doc_id = r.id
    with session_scope() as s:
        assert DocumentRepo(s).by_sha("a" * 64).id == doc_id
    with pytest.raises(IntegrityError), session_scope() as s:
        DocumentRepo(s).add(DocumentRow(sha256="a" * 64, filename="y.pdf"))


def test_catalog_search_and_facets():
    with session_scope() as s:
        repo = CatalogRepo(s)
        repo.upsert(
            plan_id="P1",
            state="TX",
            issuer="Acme",
            plan_name="Acme Silver",
            metal="Silver",
            plan_type="HMO",
            status="ready",
            deductible_individual=3000,
        )
        repo.upsert(
            plan_id="P2",
            state="TX",
            issuer="Beta",
            plan_name="Beta Gold",
            metal="Gold",
            plan_type="PPO",
            status="ready",
            deductible_individual=1000,
        )
        repo.upsert(
            plan_id="P3",
            state="FL",
            issuer="Acme",
            plan_name="Acme Bronze",
            metal="Bronze",
            plan_type="HMO",
            status="failed",
        )
    with session_scope() as s:
        repo = CatalogRepo(s)
        total, rows = repo.search(state="tx")
        assert total == 2
        assert [r.plan_id for r in repo.search(state="TX", sort="deductible")[1]] == ["P2", "P1"]
        assert repo.search(q="silver")[0] == 1
        assert repo.search(metal="silver")[0] == 1
        f = repo.facets()
        assert ("TX", 2) in f["state"] and all(st != "FL" for st, _ in f["state"])
        repo.upsert(plan_id="P1", state="TX", issuer="Acme", plan_name="Acme Silver 2", status="ready")
    with session_scope() as s:
        assert CatalogRepo(s).get("P1").plan_name == "Acme Silver 2"


def test_premium_lookup():
    with session_scope() as s:
        s.add(
            PremiumRow(
                plan_key="12345TX0010001",
                state="TX",
                rating_area="Rating Area 1",
                age="40",
                monthly_premium=420.5,
            )
        )
    with session_scope() as s:
        rows = PremiumRepo(s).lookup("12345TX0010001", "40")
        assert rows[0].monthly_premium == 420.5


def test_comparison_and_llm_log():
    from sbcx.infra.models import ComparisonRow

    with session_scope() as s:
        cid = ComparisonRepo(s).add(ComparisonRow(request={"a": 1}, result={"b": 2}, engine_version="1")).id
    record_llm_call(
        {
            "task": "summary",
            "model": "m",
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "cost_usd": 0.01,
            "latency_ms": 5,
            "outcome": "ok",
        }
    )
    with session_scope() as s:
        assert ComparisonRepo(s).get(cid).result == {"b": 2}
        assert llm_usage(s)["summary"]["calls"] >= 1
