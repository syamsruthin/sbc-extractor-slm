"""Write tests/fixtures/f1_comparison.json from the local database: the Moda TX Bronze 8700 vs Anthem
Catastrophic comparison where the discovery review found deductible-blind verdicts (F1) and a false
explanation claim (F2). Holds the two BenefitsDocuments with their catalog metadata, and the stored
request, result (engine 1.2.0) and explanation, so tests don't need the PDF corpus.

    uv run python tests/make_fixtures.py [comparison_id]"""

import json
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DB = BACKEND / "var/sbcx.db"
OUT = BACKEND / "tests/fixtures/f1_comparison.json"
CID = sys.argv[1] if len(sys.argv) > 1 else "f8c68687c8aa46229e11129fab76e0c7"


def main() -> None:
    con = sqlite3.connect(DB)
    request, result, explanation, engine = con.execute(
        "select request, result, explanation, engine_version from comparisons where id = ?", (CID,)
    ).fetchone()
    request, result = json.loads(request), json.loads(result)
    plans = []
    for did in request["document_ids"]:
        benefits, cat_id = con.execute(
            "select benefits, catalog_plan_id from documents where id = ?", (did,)
        ).fetchone()
        meta = {"metal": None, "hsa_eligible": None, "coverage_examples": None}
        if cat_id:
            metal, hsa, examples = con.execute(
                "select metal, hsa_eligible, coverage_examples from catalog_plans where plan_id = ?",
                (cat_id,),
            ).fetchone()
            meta = {
                "metal": metal,
                "hsa_eligible": None if hsa is None else bool(hsa),
                "coverage_examples": json.loads(examples) if examples else None,
            }
        plans.append(
            {"document_id": did, "catalog_plan_id": cat_id, **meta, "benefits": json.loads(benefits)}
        )
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "comparison_id": CID,
                "engine_version": engine,
                "plans": plans,
                "request": request,
                "result": result,
                "explanation": json.loads(explanation) if explanation else None,
            },
            indent=1,
        )
    )
    print("wrote", OUT)


if __name__ == "__main__":
    main()
