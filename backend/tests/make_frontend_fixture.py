"""Write frontend/src/test/fixtures/comparison.json from the engine (worked-example plans), so UI tests
run against the real response contract.   uv run python tests/make_frontend_fixture.py"""

import json
from datetime import UTC, datetime
from pathlib import Path

from sbcx.api.schemas import ComparisonResponse
from sbcx.domain.explain.generate import explain
from tests.unit.test_engine_explain import run

r = run()
req = {"document_ids": ["a", "b"], "base_document_id": "a", "inputs": {}, "scenario_ids": ["low", "moderate"]}
resp = ComparisonResponse(
    id="cmp1",
    created_at=datetime(2026, 10, 27, tzinfo=UTC),
    request=req,
    result=r,
    explanation_status="ready",
    explanation=explain(r, None, "m"),
)
out = Path(__file__).resolve().parents[2] / "frontend/src/test/fixtures/comparison.json"
out.write_text(json.dumps(resp.model_dump(mode="json"), indent=1))
print("wrote", out)
