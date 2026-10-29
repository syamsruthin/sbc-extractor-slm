"""Write frontend/src/test/fixtures/comparison.json (worked-example plans) and comparison_f1.json (the
Moda Bronze vs Anthem Catastrophic fixture) from the engine, so UI tests run against the real response
contract. comparison_v120.json is a frozen engine 1.2.0 response for backward-compatibility tests.
    uv run python tests/make_frontend_fixture.py"""

import json
from datetime import UTC, datetime
from pathlib import Path

from sbcx.api.schemas import ComparisonResponse
from sbcx.domain.explain.generate import explain
from tests.fixtures import f1, f1_compare
from tests.unit.test_engine_explain import run

OUT = Path(__file__).resolve().parents[2] / "frontend/src/test/fixtures"


def write(name: str, cid: str, req: dict, r) -> None:
    resp = ComparisonResponse(
        id=cid,
        created_at=datetime(2026, 10, 27, tzinfo=UTC),
        request=req,
        result=r,
        explanation_status="ready",
        explanation=explain(r, None, "m"),
    )
    (OUT / name).write_text(json.dumps(resp.model_dump(mode="json"), indent=1))
    print("wrote", OUT / name)


write(
    "comparison.json",
    "cmp1",
    {"document_ids": ["a", "b"], "base_document_id": "a", "inputs": {}, "scenario_ids": ["low", "moderate"]},
    run(),
)
write("comparison_f1.json", "cmpf1", f1()["request"], f1_compare())
