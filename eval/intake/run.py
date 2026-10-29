"""Usage intake evaluation (v2.1 T4.6): run every case in cases.jsonl through the intake service with the
configured OpenRouter model and report event precision/recall, count exact-match, unmodeled recall,
injection leaks, rejection rate, cost and latency. Uses a scratch var dir; nothing is stored.

    cd backend && uv run python ../eval/intake/run.py [--out report.json]"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="write per-case results here")
    args = ap.parse_args()
    os.environ["SBCX_VAR_DIR"] = tempfile.mkdtemp(prefix="sbcx-intake-eval-")
    os.environ["SBCX_LLM_MODE"] = "openrouter"
    os.environ["SBCX_INTAKE_ENABLED"] = "true"

    from sbcx.api.schemas import InterpretUsageRequest
    from sbcx.errors import AppError
    from sbcx.infra.db import init_db
    from sbcx.infra.db import session_scope
    from sbcx.infra.models import LLMCallRow
    from sbcx.services.usage import interpret

    init_db()
    cases = [json.loads(x) for x in (HERE / "cases.jsonl").read_text().splitlines() if x.strip()]
    tp = fp = fn = count_ok = un_hit = un_total = leaks = rejected = 0
    results = []
    for c in cases:
        t0 = time.perf_counter()
        try:
            r = interpret(
                InterpretUsageRequest(text=c["text"], coverage_tier=c["coverage_tier"], members=c["members"])
            )
            got = {(e.event, e.member): e.count for e in r.events}
            unmodeled = [u.quote.lower() for u in r.unmodeled]
            error = None
        except AppError as e:
            got, unmodeled, error = {}, [], e.code
            rejected += e.code == "E_INTAKE_INVALID"
        want = {(e["event"], e["member"]): e["count"] for e in c["expected_events"]}
        hit = set(got) & set(want)
        tp += len(hit)
        fp += len(set(got) - set(want))
        fn += len(set(want) - set(got))
        count_ok += sum(got[k] == want[k] for k in hit)
        if "injection" in c["tags"]:
            leaks += len(set(got) - set(want))
        for u in c["expected_unmodeled"]:
            un_total += 1
            un_hit += any(u.lower() in q or q in u.lower() for q in unmodeled)
        ok = got == want and all(
            any(u.lower() in q or q in u.lower() for q in unmodeled) for u in c["expected_unmodeled"]
        )
        results.append(
            {
                "id": c["id"],
                "ok": ok,
                "error": error,
                "got": {f"{k[0]}@{k[1]}": v for k, v in got.items()},
                "want": {f"{k[0]}@{k[1]}": v for k, v in want.items()},
                "unmodeled": unmodeled,
                "seconds": round(time.perf_counter() - t0, 1),
            }
        )
        mark = "ok " if ok else "XX "
        print(
            f"{mark}{c['id']} {error or ''} got={results[-1]['got']} want={results[-1]['want']} unmodeled={unmodeled}",
            flush=True,
        )

    with session_scope() as s:
        calls = s.query(LLMCallRow).filter(LLMCallRow.task == "usage_intake").all()
    cost = sum(x.cost_usd for x in calls)
    lat = [x.latency_ms for x in calls if x.latency_ms]
    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    print(f"\ncases {len(cases)}, fully right {sum(r['ok'] for r in results)}")
    print(
        f"event precision {prec:.2f} (target 0.90)  recall {rec:.2f} (0.80)  count exact-match {count_ok / max(tp, 1):.2f} (0.80)"
    )
    print(
        f"unmodeled recall {un_hit / max(un_total, 1):.2f} (0.80)  injection leaks {leaks} (0)  rejected (422) {rejected}"
    )
    print(
        f"LLM calls {len(calls)} (incl. retries), cost ${cost:.4f}, mean latency {sum(lat) / max(len(lat), 1) / 1000:.1f} s"
    )
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    sys.exit(main())
