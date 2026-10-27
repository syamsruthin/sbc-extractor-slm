"""Command line: `uv run sbcx <command>`. Corpus jobs use a process pool and the layout cache."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from sbcx.config import get_settings

S = get_settings()
PDF_DIR = S.data_dir / "raw/sbc_pdfs"
LAYOUT_CACHE = S.var_dir / "cache/layout"
BRANDS = str(S.config_dir / "issuer_brands.json")
EVAL_DIR = S.data_dir.parent / "eval"


def _manifest() -> dict[str, dict]:
    with open(S.data_dir / "manifest.csv") as f:
        return {r["plan_id"]: r for r in csv.DictReader(f)}


def plan_ids(which: str) -> list[str]:
    if which == "gold":
        return sorted(p.stem for p in (S.data_dir / "gold/labels").glob("*.json"))
    if which == "v14":
        man = json.loads((S.data_dir / "labels/v1.4/_manifest.json").read_text())
        return sorted(m["plan_id"] for m in man if m["status"] == "reviewed")
    if which == "all":
        return sorted(p.stem for p in PDF_DIR.glob("*.pdf"))
    return [which]


def _extract_one(pid: str) -> tuple[str, dict | None, str]:
    from sbcx.domain.extract.fallback import resolve
    from sbcx.domain.extract.run import extract_pdf

    t0 = time.perf_counter()
    try:
        pdf = PDF_DIR / f"{pid}.pdf"
        man = _MAN.get(pid) or {}
        doc, _, res = extract_pdf(
            pdf, LAYOUT_CACHE, issuer_id=pid[:5], issuer_hint=man.get("issuer"), brands_path=BRANDS
        )
        sent = 0
        if _FALLBACK:
            from sbcx.infra.llm import get_llm

            sent = resolve(doc, get_llm(), S.model_fallback, S.confidence_threshold)
        status = f"{res.source} {time.perf_counter() - t0:.1f}s fallback_cells={sent}"
        return pid, doc.benefits.model_dump(mode="json"), status
    except Exception as e:
        return pid, None, f"ERROR {type(e).__name__}: {e}"[:300]


_MAN: dict[str, dict] = {}
_FALLBACK = False


def _init_worker(fallback: bool = False) -> None:
    global _FALLBACK
    _MAN.update(_manifest())
    _FALLBACK = fallback


def run_extract(ids: list[str], workers: int, fallback: bool = False) -> dict[str, dict | None]:
    out: dict[str, dict | None] = {}
    errors = 0
    sent = 0
    with ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(fallback,)) as ex:
        for i, (pid, d, status) in enumerate(ex.map(_extract_one, ids, chunksize=2), 1):
            out[pid] = d
            if "fallback_cells=" in status:
                sent += int(status.rsplit("=", 1)[1])
            if d is None:
                errors += 1
                print(f"  {pid}: {status}", file=sys.stderr)
            if i % 50 == 0 or i == len(ids):
                print(
                    f"  {i}/{len(ids)} done, {errors} errors, {sent} cells sent to the LLM", file=sys.stderr
                )
    return out


def _load_scorer():
    spec = importlib.util.spec_from_file_location("eval_score", EVAL_DIR / "score.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def cmd_score(args: argparse.Namespace) -> None:
    ids = plan_ids(args.set)
    run_dir = EVAL_DIR / "predictions" / f"parser_v2_{args.set}{'_fallback' if args.fallback else ''}"
    run_dir.mkdir(parents=True, exist_ok=True)
    preds = run_extract(ids, args.workers, args.fallback)
    for pid, d in preds.items():
        if d is not None:
            (run_dir / f"{pid}.json").write_text(json.dumps(d, indent=1, ensure_ascii=False))
    score = _load_scorer()
    if args.set == "gold":
        report = score.score_run(run_dir)
    else:  # agreement with reviewed v1.4 labels, same field-level metrics
        ref = S.data_dir / "labels/v1.4"
        docs = {}
        for pid in ids:
            gold = json.loads((ref / f"{pid}.json").read_text())
            pred, _ = score.load_pred(run_dir / f"{pid}.json")
            docs[pid] = score.score_doc(gold, pred)
        report = {
            "run": run_dir.name,
            "n_docs": len(docs),
            "status": {},
            "json_parse_rate": 1.0,
            "schema_valid_rate": 1.0,
            "all_docs": score.summarize(docs),
            "parsed_docs": None,
        }
    (run_dir / "score.json").write_text(json.dumps(report, indent=2))
    score.print_report(report)


def cmd_extract(args: argparse.Namespace) -> None:
    _init_worker()
    for pid in args.ids:
        pid = Path(pid).stem
        _, d, status = _extract_one(pid)
        print(json.dumps(d, indent=1, ensure_ascii=False) if d else status)


def cmd_layout(args: argparse.Namespace) -> None:
    ids = plan_ids("all") if args.all else [Path(i).stem for i in args.ids]
    t0 = time.perf_counter()
    with ProcessPoolExecutor(args.workers) as ex:
        res = list(ex.map(_layout_one, ids, chunksize=4))
    bad = [r for r in res if r]
    print(f"{len(ids)} layouts in {time.perf_counter() - t0:.0f}s, {len(bad)} failures")
    for b in bad:
        print(" ", b)


def _layout_one(pid: str) -> str | None:
    from sbcx.domain.parse.layout import get_layout

    try:
        get_layout(PDF_DIR / f"{pid}.pdf", LAYOUT_CACHE)
        return None
    except Exception as e:
        return f"{pid}: {type(e).__name__}: {e}"[:200]


def cmd_ingest_catalog(args: argparse.Namespace) -> None:
    from sbcx.services.catalog import ingest

    stats = ingest(
        PDF_DIR, S.data_dir / "raw/puf/plan-attributes-puf.csv", args.workers, args.limit, args.ids or None
    )
    print(json.dumps(stats))


def cmd_load_premiums(args: argparse.Namespace) -> None:
    from sbcx.services.catalog import load_premiums

    path = Path(args.file) if args.file else S.var_dir / "rate-puf.zip"
    if not path.exists():
        import httpx

        print(f"downloading {args.url} -> {path}", file=sys.stderr)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        with httpx.stream("GET", args.url, timeout=600, follow_redirects=True) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
        tmp.replace(path)
    print(f"loaded {load_premiums(path)} premium rows")


def cmd_openapi(_: argparse.Namespace) -> None:
    from sbcx.main import create_app

    print(json.dumps(create_app().openapi(), indent=2))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="sbcx")
    sub = p.add_subparsers(dest="cmd", required=True)
    workers = max(1, (os.cpu_count() or 2) - 1)

    a = sub.add_parser("layout", help="build/cache layouts for the corpus")
    a.add_argument("ids", nargs="*")
    a.add_argument("--all", action="store_true")
    a.add_argument("--workers", type=int, default=workers)
    a.set_defaults(fn=cmd_layout)

    a = sub.add_parser("extract", help="print the extraction for corpus plan ids")
    a.add_argument("ids", nargs="+")
    a.set_defaults(fn=cmd_extract)

    a = sub.add_parser("score", help="score the parser on gold or v1.4 reviewed labels")
    a.add_argument("--set", choices=["gold", "v14", "all"], default="gold")
    a.add_argument("--fallback", action="store_true", help="apply the LLM cell fallback (OpenRouter)")
    a.add_argument("--workers", type=int, default=workers)
    a.set_defaults(fn=cmd_score)

    a = sub.add_parser("ingest-catalog", help="extract the local SBC corpus into the plan catalog")
    a.add_argument("ids", nargs="*", help="only these plan ids")
    a.add_argument("--limit", type=int)
    a.add_argument("--workers", type=int, default=workers)
    a.set_defaults(fn=cmd_ingest_catalog)

    from sbcx.services.catalog import RATE_PUF_URL

    a = sub.add_parser("load-premiums", help="download (if needed) and load the CMS Rate PUF")
    a.add_argument("--file", help="local rate-puf.zip or csv")
    a.add_argument("--url", default=RATE_PUF_URL)
    a.set_defaults(fn=cmd_load_premiums)

    a = sub.add_parser("openapi", help="print the OpenAPI spec")
    a.set_defaults(fn=cmd_openapi)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
