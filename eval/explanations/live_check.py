"""Live check of explanation prompt v3 + claim checks (v2.1 T1.9): re-create stored comparisons with the
current engine on a COPY of the database, generate explanations with the configured OpenRouter model, and
print source, grounding and the text for human review. Spends a few cents of OpenRouter credit.

    cd backend && uv run python ../eval/explanations/live_check.py --out <scratch dir> <comparison id>..."""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="var/sbcx.db")
    ap.add_argument("--out", required=True, help="scratch directory for the database copy")
    ap.add_argument("ids", nargs="+")
    args = ap.parse_args()
    var = Path(args.out)
    var.mkdir(parents=True, exist_ok=True)
    shutil.copy(args.db, var / "sbcx.db")
    os.environ["SBCX_VAR_DIR"] = str(var)  # before sbcx reads settings
    os.environ["SBCX_LLM_MODE"] = "openrouter"

    from sbcx.domain.comparison import ComparisonRequest
    from sbcx.infra.db import init_db, session_scope
    from sbcx.infra.models import ComparisonRow
    from sbcx.services import comparison as svc
    from sbcx.services.explanation import generate_explanation

    import sbcx.domain.explain.generate as gen

    rejected: list[list[str]] = []
    validate = gen._validate

    def recording(e, facts, result=None):  # keep each rejected attempt's reasons for the report
        r = validate(e, facts, result)
        if not r.ok:
            rejected.append(r.violations + r.policy_violations + r.claim_violations)
        return r

    gen._validate = recording
    init_db()
    report = []
    for cid in args.ids:
        with session_scope() as s:
            row = s.get(ComparisonRow, cid)
            assert row is not None, cid
            req = ComparisonRequest.model_validate({**row.request, "explain": True})
        rejected.clear()
        new = svc.create(req)
        generate_explanation(new.id)
        got = svc.get(new.id)
        e = got.explanation
        assert e is not None, got.explanation_status
        report.append(
            {
                "from": cid,
                "id": new.id,
                "plans": [p.plan_name for p in got.result.plans],
                "source": e.source,
                "grounding": e.grounding.model_dump(),
                "rejected_attempts": list(rejected),
                "content": e.content.model_dump(),
            }
        )
        print(
            f"{cid[:8]} -> {e.source:9} ok={e.grounding.ok} claims={e.grounding.claim_violations}", flush=True
        )
        for attempt in rejected:
            print(f"    rejected: {attempt}", flush=True)
    (var / "live_check.json").write_text(json.dumps(report, indent=1))
    by = {k: sum(r["source"] == k for r in report) for k in ("llm", "llm_retry", "template")}
    print(f"\n{len(report)} explanations: {by}; details in {var / 'live_check.json'}")


if __name__ == "__main__":
    sys.exit(main())
