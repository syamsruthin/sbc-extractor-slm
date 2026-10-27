"""LayoutDoc -> SBCExtraction. Mirrors audit_tools/gen.py: parse the markdown view; when it misses
3+ services (or has no drug tiers) also parse the pdfplumber table view and keep the better one."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from sbcx.domain.parse.build import build
from sbcx.domain.parse.exclusions import items as excl_items
from sbcx.domain.parse.layout import LayoutDoc
from sbcx.domain.sbc import SBCExtraction, normalize

KEYS = [
    "plan_name",
    "issuer",
    "plan_type",
    "coverage_period",
    "deductible",
    "out_of_pocket_limit",
    "services_before_deductible",
    "referral_required_for_specialist",
    "services",
    "drug_tiers",
    "excluded_services",
]


@dataclass
class ParseResult:
    extraction: SBCExtraction
    raw: dict[str, Any]  # build() output incl. '_o' (anchored rows) and '_src' (chosen cells)
    source: str  # "md" | "pdf"
    missing_services: int
    warnings: list[str] = field(default_factory=list)


@lru_cache
def load_brands(path: str) -> dict[str, str]:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {}


def _nbad(d: dict) -> int:
    return sum(v["in_network"] is None for v in d["services"].values()) + (4 if not d["drug_tiers"] else 0)


def _clean(d: dict) -> dict:
    """gen.py clean(): drop mail-order notes on drug tiers, '$0 / No deductible', plan_type fallback."""
    o = {k: d[k] for k in KEYS}
    for t in o["drug_tiers"]:
        for nw in ("in_network", "out_of_network"):
            c = t["retail"][nw]
            if (
                c
                and c.get("note")
                and re.search(
                    r"(?i)mail|retail|participating|supply|home delivery|prescription\b(?!s)|insulin|formulary|pharmacy",
                    c["note"],
                )
            ):
                c["note"] = None
    q = d["_o"]["_q"]
    if o["deductible"]["in_network"] is None and re.match(r"(?i)^\s*(no deductible|\$0\b)", q["ded"] or ""):
        o["deductible"]["in_network"] = dict(individual=0.0, family=None)
    if o["plan_type"] not in ("HMO", "PPO", "EPO", "POS"):
        m = re.search(
            r"Plan Type\W{0,8}(?:HDHP\W{0,3})?(HMO|PPO|EPO|POS)",
            d["_o"]["_head"] + " " + (o["plan_type"] or ""),
        )
        if m:
            o["plan_type"] = m.group(1)
        elif o["plan_type"]:
            m2 = re.search(r"(HMO|PPO|EPO|POS)", o["plan_type"])
            o["plan_type"] = m2.group(1) if m2 else None
    if o["plan_name"]:
        o["plan_name"] = (
            re.sub(
                r"^Matthew Thornton Health Plan, Inc\.\s*/\s*Anthem Blue Cross and Blue Shield\s+",
                "",
                o["plan_name"],
            )
            or o["plan_name"]
        )
    return o


def _dashfix(d: dict, md: str) -> None:
    """Restore en dashes in drug tier names as printed ("Tier 1 – Generic")."""
    txt = re.sub(r"\s+", " ", md)
    for t in d["drug_tiers"]:
        if "-" not in t["name"]:
            continue
        pat = re.sub(r"\\-", "[-–—]", re.escape(t["name"])).replace("\\ ", " ")
        m = re.search(pat.replace(" ", r"\s*"), txt)
        if m and "–" in m.group(0):
            t["name"] = re.sub(r"\s+", " ", m.group(0))


def parse_layout(
    layout: LayoutDoc,
    pdf_path: str | Path | None = None,
    issuer_id: str | None = None,
    issuer_hint: str | None = None,
    brands_path: str | None = None,
) -> ParseResult:
    brands = load_brands(brands_path) if brands_path else {}
    excluded = excl_items(layout.excl, str(pdf_path) if pdf_path else "") if layout.excl else []
    kw: dict[str, Any] = dict(
        excluded=excluded,
        issuer_id=issuer_id,
        issuer_hint=issuer_hint,
        brands=brands,
        page1_text=layout.page1_text,
    )
    warnings: list[str] = []
    d = build(layout.md, **kw)
    source = "md"
    if _nbad(d) >= 3:
        try:
            d2 = build(layout.pdf_rows, **kw)
            if _nbad(d2) < _nbad(d):
                d, source = d2, "pdf"
        except Exception as e:  # the table view is a second chance; keep the markdown result
            warnings.append(f"table view failed: {type(e).__name__}")
    _dashfix(d, layout.md)
    label = _clean(d)
    ext = normalize(SBCExtraction.model_validate(label))
    missing = sum(v["in_network"] is None for v in d["services"].values())
    return ParseResult(extraction=ext, raw=d, source=source, missing_services=missing, warnings=warnings)
