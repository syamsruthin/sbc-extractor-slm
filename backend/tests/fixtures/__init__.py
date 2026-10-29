"""Comparison fixtures exported from a real local database by tests/make_fixtures.py."""

import json
from functools import lru_cache
from pathlib import Path

from sbcx.config import get_settings
from sbcx.domain.benefits import BenefitsDocument
from sbcx.domain.compare.config import load_prices, load_scenarios
from sbcx.domain.compare.engine import PlanInput, compare
from sbcx.domain.comparison import ComparisonRequest, ComparisonResult

HERE = Path(__file__).resolve().parent


@lru_cache
def f1() -> dict:
    """Moda TX Bronze 8700 (base, A) vs Anthem Catastrophic (B), stored with engine 1.2.0."""
    return json.loads((HERE / "f1_comparison.json").read_text())


def f1_inputs() -> list[PlanInput]:
    return [
        PlanInput(
            document_id=p["document_id"],
            doc=BenefitsDocument.model_validate(p["benefits"]),
            catalog_plan_id=p["catalog_plan_id"],
            metal=p["metal"],
            coverage_examples=p["coverage_examples"],
            hsa_eligible=p["hsa_eligible"],
        )
        for p in f1()["plans"]
    ]


def f1_compare(**overrides) -> ComparisonResult:
    s = get_settings()
    req = ComparisonRequest.model_validate({**f1()["request"], **overrides})
    return compare(f1_inputs(), req, load_scenarios(str(s.config_dir)), load_prices(str(s.config_dir)))


def seed_f1() -> list[str]:
    """Store the F1 plans as ready catalog documents (same ids as the fixture) and return their document ids."""
    from sbcx.infra.db import session_scope
    from sbcx.infra.models import CatalogPlanRow, DocumentRow

    ids = []
    with session_scope() as s:
        for p in f1()["plans"]:
            b = p["benefits"]["benefits"]
            s.add(
                DocumentRow(
                    id=p["document_id"],
                    sha256=p["document_id"].ljust(64, "0"),
                    filename=f"{p['catalog_plan_id']}.pdf",
                    source="catalog",
                    status="ready",
                    plan_name=b.get("plan_name"),
                    issuer=b.get("issuer"),
                    plan_type=b.get("plan_type"),
                    summaries_status="skipped",
                    benefits=p["benefits"],
                    catalog_plan_id=p["catalog_plan_id"],
                )
            )
            s.flush()
            s.add(
                CatalogPlanRow(
                    plan_id=p["catalog_plan_id"],
                    state=p["catalog_plan_id"][5:7],
                    issuer=b.get("issuer") or "",
                    plan_name=b.get("plan_name") or "",
                    metal=p["metal"],
                    plan_type=b.get("plan_type"),
                    document_id=p["document_id"],
                    coverage_examples=p["coverage_examples"],
                    hsa_eligible=p["hsa_eligible"],
                    status="ready",
                )
            )
            ids.append(p["document_id"])
    return ids
