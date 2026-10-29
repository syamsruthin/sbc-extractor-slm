"""Marketplace plan catalog: ingest the local SBC corpus with CMS PUF metadata, search it, and look up
premiums from the CMS Rate PUF."""

from __future__ import annotations

import csv
import io
import logging
import re
import sys
import zipfile
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from sbcx.api.schemas import (
    CatalogFacets,
    CatalogPage,
    CatalogPlan,
    FacetValue,
    HouseholdMember,
    HouseholdQuote,
    PremiumQuote,
    PremiumQuotes,
    RatingArea,
    RatingAreas,
)
from sbcx.config import get_settings
from sbcx.domain.benefits import BenefitsDocument
from sbcx.domain.compare.cost_model import DeductibleHints, deductible_hints
from sbcx.errors import not_found
from sbcx.infra.db import init_db, session_scope
from sbcx.infra.models import DocumentRow, PremiumRow
from sbcx.infra.repos import CatalogRepo, DocumentRepo, PremiumRepo
from sbcx.versions import PARSER_VERSION

logger = logging.getLogger("sbcx.catalog")
RATE_PUF_URL = "https://download.cms.gov/marketplace-puf/2026/rate-puf.zip"
EXAMPLES = {
    "having_a_baby": "HavingaBaby",
    "managing_diabetes": "HavingDiabetes",
    "simple_fracture": "HavingSimplefracture",
}


def _money(v: str | None) -> float | None:
    m = re.search(r"[\d,]+(?:\.\d+)?", v or "")
    return float(m.group(0).replace(",", "")) if m else None


def puf_metadata(puf_csv: Path, plan_ids: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with open(puf_csv, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            pid = r["PlanId"]
            if pid not in plan_ids or pid in out:
                continue
            examples = {}
            for key, col in EXAMPLES.items():
                parts = {
                    k: _money(r.get(f"SBC{col}{k.capitalize()}"))
                    for k in ("deductible", "copayment", "coinsurance", "limit")
                }
                if any(v is not None for v in parts.values()):
                    examples[key] = parts | {"total": round(sum(v or 0 for v in parts.values()), 2)}
            out[pid] = {
                "plan_year": int(r.get("BusinessYear") or 2026),
                "state": r["StateCode"],
                "issuer": r["IssuerMarketPlaceMarketingName"],
                "plan_name": r.get("PlanVariantMarketingName") or r["PlanMarketingName"],
                "metal": r["MetalLevel"],
                "plan_type": r["PlanType"],
                "sbc_url": r.get("URLForSummaryofBenefitsCoverage"),
                "coverage_examples": examples or None,
                "hsa_eligible": {"yes": True, "no": False}.get(
                    (r.get("IsHSAEligible") or "").strip().lower()
                ),
            }
    return out


def _extract_job(args: tuple[str, str, str | None]) -> tuple[str, dict | None, str | None]:
    pid, pdf, issuer = args
    from sbcx.domain.extract.run import extract_pdf
    from sbcx.domain.parse.layout import sha256_bytes
    from sbcx.infra.storage import layout_cache_dir

    s = get_settings()
    try:
        sha = sha256_bytes(Path(pdf).read_bytes())
        doc, _, _ = extract_pdf(
            pdf,
            layout_cache_dir(),
            sha,
            issuer_id=pid[:5],
            issuer_hint=issuer,
            brands_path=str(s.config_dir / "issuer_brands.json"),
        )
        return pid, doc.model_dump(mode="json"), None
    except Exception as e:
        return pid, None, f"{type(e).__name__}: {e}"[:300]


def ingest(
    pdf_dir: Path, puf_csv: Path, workers: int = 4, limit: int | None = None, only: list[str] | None = None
) -> dict:
    """Extract every local SBC into the catalog. Deterministic only (no LLM); summaries are made on
    demand when a plan is opened."""
    init_db()
    pdfs = {p.stem: p for p in sorted(pdf_dir.glob("*.pdf"))}
    if only:
        pdfs = {k: v for k, v in pdfs.items() if k in set(only)}
    meta = puf_metadata(puf_csv, set(pdfs))
    with session_scope() as sess:
        done = {
            r.plan_id
            for r in CatalogRepo(sess).search(ready_only=True, limit=10**6)[1]
            if (d := DocumentRepo(sess).get(r.document_id or "")) and d.parser_version == PARSER_VERSION
        }
    if done:  # current extractions are kept, but PUF metadata (e.g. hsa_eligible) is refreshed
        with session_scope() as sess:
            repo = CatalogRepo(sess)
            for pid in done:
                row = repo.get(pid)
                if row is not None and pid in meta:
                    for k, v in meta[pid].items():
                        setattr(row, k, v)
    todo = [(pid, str(p), meta.get(pid, {}).get("issuer")) for pid, p in pdfs.items() if pid not in done]
    if limit:
        todo = todo[:limit]
    stats = {"total": len(pdfs), "skipped_current": len(done), "ok": 0, "failed": 0, "no_metadata": 0}
    with ProcessPoolExecutor(workers) as ex:
        for i, (pid, doc, err) in enumerate(ex.map(_extract_job, todo, chunksize=2), 1):
            _store(pid, pdfs[pid], meta.get(pid), doc, err, stats)
            if i % 50 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}  ok={stats['ok']} failed={stats['failed']}", file=sys.stderr)
    return stats


def _store(pid: str, pdf: Path, m: dict | None, doc: dict | None, err: str | None, stats: dict) -> None:
    from sbcx.domain.parse.layout import sha256_bytes

    if m is None:
        stats["no_metadata"] += 1
        b = (doc or {}).get("benefits") or {}
        m = {
            "plan_year": 2026,
            "state": pid[5:7],
            "issuer": b.get("issuer") or "Unknown",
            "plan_name": b.get("plan_name") or pid,
            "metal": None,
            "plan_type": b.get("plan_type"),
            "sbc_url": None,
            "coverage_examples": None,
        }
    sha = sha256_bytes(pdf.read_bytes())
    with session_scope() as sess:
        docs = DocumentRepo(sess)
        row = docs.by_sha(sha)
        if row is None:
            row = docs.add(DocumentRow(sha256=sha, filename=pdf.name, source="catalog"))
        from sbcx.infra.storage import save_pdf

        save_pdf(sha, pdf.read_bytes())
        row.catalog_plan_id = pid
        if doc is None:
            row.status, row.error_code, row.error_message = "failed", "E_EXTRACTION_FAILED", err
            stats["failed"] += 1
        else:
            b = doc["benefits"]
            row.status, row.error_code, row.error_message = "ready", None, None
            row.benefits, row.parser_version = doc, PARSER_VERSION
            row.plan_name, row.issuer, row.plan_type = b["plan_name"], b["issuer"], b["plan_type"]
            row.doc_confidence, row.npages = doc["doc_confidence"], doc["extras"]["npages"]
            row.summaries_status = "pending"
            stats["ok"] += 1
        ded = (((doc or {}).get("benefits") or {}).get("deductible") or {}).get("in_network") or {}
        oop = (((doc or {}).get("benefits") or {}).get("out_of_pocket_limit") or {}).get("in_network") or {}
        CatalogRepo(sess).upsert(
            plan_id=pid,
            document_id=row.id,
            status="ready" if doc else "failed",
            deductible_individual=ded.get("individual"),
            oop_individual=oop.get("individual"),
            **m,
        )


# ---- premiums (CMS Rate PUF) ----


def _rate_rows(path: Path) -> Iterator[dict[str, str]]:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            with z.open(name) as f:
                yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""))
    else:
        with open(path, encoding="utf-8-sig", newline="") as f:
            yield from csv.DictReader(f)


def load_premiums(path: Path) -> int:
    """Load individual (non-tobacco) monthly premiums for plans in the catalog."""
    init_db()
    with session_scope() as sess:
        keys = {r.plan_id[:14] for r in CatalogRepo(sess).search(ready_only=False, limit=10**6)[1]}
        sess.query(PremiumRow).delete()
    batch, n = [], 0
    for r in _rate_rows(path):
        key = r.get("PlanId", "")[:14]
        if key not in keys or not r.get("IndividualRate"):
            continue
        try:
            rate = float(r["IndividualRate"])
        except ValueError:
            continue
        if rate <= 0 or rate > 9000:  # 9999 is a placeholder in the PUF
            continue
        batch.append(
            PremiumRow(
                plan_key=key,
                state=r.get("StateCode", ""),
                rating_area=r.get("RatingAreaId", ""),
                age=r.get("Age", ""),
                monthly_premium=rate,
            )
        )
        if len(batch) >= 5000:
            n += _flush(batch)
    n += _flush(batch)
    return n


def _flush(batch: list[PremiumRow]) -> int:
    if not batch:
        return 0
    with session_scope() as sess:
        sess.add_all(batch)
    k = len(batch)
    batch.clear()
    return k


# ---- queries ----


def _plan(r) -> CatalogPlan:
    return CatalogPlan(
        plan_id=r.plan_id,
        plan_year=r.plan_year,
        state=r.state,
        issuer=r.issuer,
        plan_name=r.plan_name,
        metal=r.metal,
        plan_type=r.plan_type,
        document_id=r.document_id,
        deductible_individual=r.deductible_individual,
        oop_individual=r.oop_individual,
    )


def search(**kw: Any) -> CatalogPage:
    with session_scope() as sess:
        total, rows = CatalogRepo(sess).search(**kw)
        return CatalogPage(
            total=total, offset=kw.get("offset", 0), limit=kw.get("limit", 25), items=[_plan(r) for r in rows]
        )


def get_plan(plan_id: str) -> CatalogPlan:
    with session_scope() as sess:
        r = CatalogRepo(sess).get(plan_id)
        if r is None:
            raise not_found("Catalog plan", plan_id)
        return _plan(r)


def plan_hints(doc: BenefitsDocument, catalog_plan_id: str | None) -> DeductibleHints:
    """Deductible hints for a stored document, with the catalog's metal and HSA flag when it is a catalog plan
    (the same evidence comparisons use)."""
    metal = hsa = None
    if catalog_plan_id:
        with session_scope() as s:
            if c := CatalogRepo(s).get(catalog_plan_id):
                metal, hsa = c.metal, c.hsa_eligible
    return deductible_hints(doc.benefits, metal, hsa)


def coverage_examples(plan_id: str) -> dict | None:
    with session_scope() as sess:
        r = CatalogRepo(sess).get(plan_id)
        return r.coverage_examples if r else None


def facets() -> CatalogFacets:
    with session_scope() as sess:
        f = CatalogRepo(sess).facets()
        loaded = PremiumRepo(sess).count() > 0
    return CatalogFacets(
        **{k: [FacetValue(value=str(v), count=c) for v, c in vals] for k, vals in f.items()},
        premiums_loaded=loaded,
    )


def premiums(plan_id: str, age: str = "40", rating_area: str | None = None) -> PremiumQuotes:
    get_plan(plan_id)
    with session_scope() as sess:
        rows = PremiumRepo(sess).lookup(plan_id[:14], age, rating_area)
        return PremiumQuotes(
            items=[
                PremiumQuote(
                    plan_id=plan_id, age=r.age, rating_area=r.rating_area, monthly_premium=r.monthly_premium
                )
                for r in rows
            ]
        )


def age_band(age: int) -> str:
    """CMS Rate PUF age band for an age."""
    if age < 15:
        return "0-14"
    if age >= 64:
        return "64 and over"
    return str(age)


def counted_members(ages: list[int]) -> list[bool]:
    """Which members a family premium counts: everyone 21 and over, and at most the 3 oldest children under 21
    (CMS family rating rule, 45 CFR 147.102(c)(4); v2.1 decision D2)."""
    children = sorted((i for i, a in enumerate(ages) if a < 21), key=lambda i: -ages[i])
    skip = set(children[3:])
    return [i not in skip for i in range(len(ages))]


def rating_areas(state: str) -> RatingAreas:
    st = state.upper()
    with session_scope() as sess:
        rows = PremiumRepo(sess).rating_areas(st)

    def num(name: str) -> tuple[int, str]:
        m = re.search(r"(\d+)\s*$", name)
        return (int(m.group(1)) if m else 10**6, name)

    return RatingAreas(
        state=st,
        items=[RatingArea(rating_area=a, plans_priced=n) for a, n in sorted(rows, key=lambda r: num(r[0]))],
    )


def household_quote(plan_id: str, rating_area: str, ages: list[int]) -> HouseholdQuote:
    get_plan(plan_id)
    bands = [age_band(a) for a in ages]
    counted = counted_members(ages)
    with session_scope() as sess:
        rates = PremiumRepo(sess).rates(plan_id[:14], rating_area, sorted(set(bands)))
    members = [
        HouseholdMember(age=a, band=b, monthly_premium=rates.get(b), counted=c)
        for a, b, c in zip(ages, bands, counted, strict=True)
    ]
    missing = [m.age for m in members if m.counted and m.monthly_premium is None]
    total = None if missing else round(sum(m.monthly_premium or 0.0 for m in members if m.counted), 2)
    return HouseholdQuote(
        plan_id=plan_id, rating_area=rating_area, members=members, monthly_total=total, missing_ages=missing
    )
