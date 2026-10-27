"""ParseResult -> BenefitsDocument: provenance (page, source text, reasons), extras (limitations,
deductible type), business-rule warnings and per-field confidence."""

from __future__ import annotations

import re

from sbcx.domain.benefits import (
    BenefitsDocument,
    BenefitsExtras,
    DeductibleType,
    FieldMeta,
    Source,
    Versions,
)
from sbcx.domain.extract import rules
from sbcx.domain.parse.cells import PRICE
from sbcx.domain.parse.layout import LayoutDoc
from sbcx.domain.parse.pipeline import ParseResult
from sbcx.domain.parse.textnorm import SVK, norm
from sbcx.versions import GUIDELINE_VERSION, PARSER_VERSION, SCHEMA_VERSION

LEAVES = ("covered", "copay", "coinsurance_pct", "deductible_applies", "note")

# Confidence penalties (LLD §3.8). Multiplied; tuned on the reviewed v1.4 docs.
PENALTY = {
    "packed_row": 0.80,  # two services shared one table row
    "continued_row": 0.85,  # row stitched across a page break
    "multi_part": 0.85,  # cell had several prices; the rest went to the note
    "table_view": 0.85,  # came from the pdfplumber view (markdown view missed rows)
    "covered_no_price": 0.55,
    "missing_row": 0.40,  # row not found at all
    "rule_failed": 0.50,
    "deductible_unstated": 0.95,
}


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9$%]", "", s.lower())


def page_of(text: str | None, page_keys: list[str]) -> int | None:
    """1-based page where the source text appears (first 30 significant chars)."""
    if not text or not page_keys:
        return None
    k = _key(norm(text))[:30]
    if len(k) < 4:
        return None
    for i, p in enumerate(page_keys):
        if k in p:
            return i + 1
    k = k[:12]
    for i, p in enumerate(page_keys):
        if k in p:
            return i + 1
    return None


def deductible_type(md: str) -> DeductibleType:
    t = re.sub(r"\s+", " ", norm(md)).lower()
    if re.search(r"each family member must meet (their|his or her) own individual deductible", t):
        return DeductibleType.embedded
    if re.search(r"(overall|entire) family deductible must be met before", t):
        return DeductibleType.aggregate
    return DeductibleType.unknown


def _n_prices(s: str | None) -> int:
    return len(PRICE.findall(s or ""))


def assemble(layout: LayoutDoc, res: ParseResult, page_texts: list[str] | None = None) -> BenefitsDocument:
    ext = res.extraction
    raw = res.raw
    svc_rows = raw["_o"]["_svc"]
    src = raw.get("_src", {})
    q = raw["_o"]["_q"]
    keys = [_key(p) for p in (page_texts or [])]
    prov: dict[str, FieldMeta] = {}
    base_pen = PENALTY["table_view"] if res.source == "pdf" else 1.0

    def put(path: str, text: str | None, conf: float, reasons: list[str], trace: list[str] | None = None):
        prov[path] = FieldMeta(
            page=page_of(text, keys),
            raw_text=(text or None) and text[:600],
            source=Source.parser,
            confidence=round(max(0.0, min(1.0, conf)), 3),
            reasons=reasons,
            rule_trace=trace or [],
        )

    # page 1 answers
    for name, text in (("deductible", q.get("ded")), ("out_of_pocket_limit", q.get("oop"))):
        for net in ("in_network", "out_of_network"):
            for part in ("individual", "family"):
                put(f"{name}.{net}.{part}", text, base_pen, [])
    put("services_before_deductible", q.get("bef"), 1.0, [])
    put("referral_required_for_specialist", q.get("ref"), 1.0, [])
    for f in ("plan_name", "issuer", "plan_type", "coverage_period"):
        put(f, raw["_o"].get("_head"), 1.0, [])

    limitations: dict[str, str] = {}
    for k in SVK:
        row = svc_rows.get(k)
        ins, oos, lim = src.get(k, (None, None, None))
        if lim:
            limitations[k] = norm(lim)
        reasons_row = []
        if row is None:
            reasons_row.append("missing_row")
        else:
            if row.get("packed"):
                reasons_row.append("packed_row")
            if row.get("cont"):
                reasons_row.append("continued_row")
        for net, text in (("in_network", ins), ("out_of_network", oos)):
            cell = getattr(getattr(ext.services, k), net)
            reasons = list(reasons_row)
            if _n_prices(text) > 2 or (cell and cell.note and _n_prices(cell.note)):
                reasons.append("multi_part")
            if cell and cell.covered and cell.copay is None and cell.coinsurance_pct is None:
                reasons.append("covered_no_price")
            if cell and cell.covered and cell.deductible_applies is None and (cell.coinsurance_pct or 0) > 0:
                reasons.append("deductible_unstated")
            conf = base_pen
            for r in reasons:
                conf *= PENALTY[r]
            for leaf in LEAVES:
                put(f"services.{k}.{net}.{leaf}", text, conf, reasons)

    for i, t in enumerate(ext.drug_tiers):
        ins, oos, lim = src.get(f"t{i + 1}", (None, None, None))
        for net, text in (("in_network", ins), ("out_of_network", oos)):
            for leaf in LEAVES:
                put(f"drug_tiers[{i}].retail.{net}.{leaf}", text, base_pen, [])
        put(f"drug_tiers[{i}].name", t.name, 1.0, [])
        put(f"drug_tiers[{i}].category", t.name, 1.0, [])

    anchored = 26 - res.missing_services
    warnings = rules.check(ext, anchored)
    for w in warnings:
        if not w.path:
            continue
        for p, m in prov.items():
            if p.startswith(w.path):
                m.confidence = round(m.confidence * PENALTY["rule_failed"], 3)
                if "rule_failed" not in m.reasons:
                    m.reasons.append("rule_failed")

    p0 = [
        m.confidence
        for p, m in prov.items()
        if p.startswith(("deductible.in", "out_of_pocket_limit.in", "services."))
    ]
    doc_conf = round(sum(p0) / len(p0), 3) if p0 else 0.0
    drug_lim = next((norm(src[k][2]) for k in sorted(src) if k.startswith("t") and src[k][2]), None)
    return BenefitsDocument(
        sha256=layout.sha256,
        versions=Versions(
            schema_version=SCHEMA_VERSION, parser_version=PARSER_VERSION, guideline_version=GUIDELINE_VERSION
        ),
        benefits=ext,
        extras=BenefitsExtras(
            deductible_type=deductible_type(layout.md),
            limitations=limitations,
            drug_limitations=drug_lim,
            layout_source=res.source,
            anchored_services=anchored,
            npages=layout.npages,
        ),
        provenance=prov,
        warnings=warnings,
        doc_confidence=doc_conf,
    )
