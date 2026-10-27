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
from sbcx.domain.sbc import SBCExtraction

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


def normalize_v14(label: SBCExtraction) -> SBCExtraction:
    """Label conventions v1.4 (data/labels/v1.4/README.md). Unlike the v1.2-era schema.normalize(),
    "0% coinsurance" keeps copay null: only "No charge" / "$0 copay" mean 0/0. Zero rules are
    already applied per cell by costs.cost(); this adds the plan-info rules and drops a 0 that sits
    next to a real price ("$40 copay" is not "$40 copay then 0%")."""
    if label.plan_type:
        types = [t for t in ("HMO", "PPO", "EPO", "POS") if t in label.plan_type.upper().split()]
        if len(types) == 1:
            label.plan_type = types[0]
    if label.plan_name and label.issuer and ":" in label.plan_name:
        prefix, rest = label.plan_name.split(":", 1)
        if prefix.strip().lower() == label.issuer.strip().lower() and rest.strip():
            label.plan_name = rest.strip()
    cells = []
    for _, svc in label.services:
        cells += [svc.in_network, svc.out_of_network]
    for t in label.drug_tiers:
        cells += [t.retail.in_network, t.retail.out_of_network]
    for c in cells:
        if c is None or not c.covered:
            continue
        if c.copay and c.coinsurance_pct == 0:
            c.coinsurance_pct = None
        elif c.coinsurance_pct and c.copay == 0:
            c.copay = None
    return label


def _fill_missing_rows(d: dict, d2: dict) -> None:
    """Rows the markdown view lost entirely (pymupdf4llm sometimes drops a table row) are taken from the
    pdfplumber table view (audit 2026-10-27). Only whole missing rows: filling every empty cell from the
    table view was tried and lowered agreement, because its rows misalign more often."""
    for k, svc in d["services"].items():
        if k in d["_o"]["_svc"] or svc["in_network"] is not None or svc["out_of_network"] is not None:
            continue
        other = d2["services"].get(k) or {}
        if other.get("in_network") is not None:
            d["services"][k] = other
            d.setdefault("_filled", []).append(k)


_PIC = re.compile(r"<!-- Start of picture text -->(.*?)<!-- End of picture text -->", re.S)
_PRICE_START = re.compile(
    r"(?=\b(?:no charge|not covered|not applicable|no cost)\b|\$\s?\d|\b\d+(?:\.\d+)?\s?%)", re.I
)


def picture_rows(md: str) -> str:
    """pymupdf4llm sometimes renders a benefits table as "picture text": rows survive as plain lines
    ("Children's dental check-up Not Covered Not Covered None"). Turn lines that start with a known service
    label into pipe rows so the normal anchoring and column rules read them (audit 2026-10-27)."""
    from sbcx.domain.parse.textnorm import SV

    labels = [
        re.compile(
            r"^\s*[^$%\d|]{0,30}?(" + rx.lstrip("^") + r")[^$%\d|]{0,60}?(?=" + _PRICE_START.pattern + r")",
            re.I,
        )
        for _, rx in SV
    ]

    def convert(block: re.Match) -> str:
        out = []
        for line in block.group(1).split("<br>"):
            for lab in labels:
                m = lab.match(line)
                if not m:
                    continue
                rest = line[m.end() :]
                parts = [x.strip() for x in _PRICE_START.split(rest) if x.strip()]
                if parts:
                    cells = [m.group(0).strip(), *parts[:2], " ".join(parts[2:])]
                    out.append("||" + "|".join(cells) + "|")
                break
        return block.group(0) + ("\n" + "\n".join(out) + "\n" if out else "")

    return _PIC.sub(convert, md)


_COMMON_WORDS = {
    "health",
    "silver",
    "bronze",
    "standard",
    "select",
    "individual",
    "family",
    "premier",
    "value",
    "choice",
}


def clean_plan_name(name: str | None) -> str | None:
    """Generic header-artifact cleanup for plan names (audit 2026-10-27). Display only."""
    if not name:
        return name
    x = name.split(" | ")[0]  # header text after a table pipe
    x = re.sub(r"(?i)\s+(multi plan type|plan type)\b.*$", "", x)
    x = re.sub(r"(?i)(\s+subscriber/family dependent)+\s*$", "", x)
    x = re.sub(r"^\s*\((?:domiciled|underwritten)[^)]*\)\s*", "", x, flags=re.I)
    x = re.sub(r"^\s*[–—\-:|]+\s*", "", x)
    x = re.sub(r"^(\w+) \1\b", r"\1", x)  # "Wellpoint Wellpoint Essential"
    m = re.match(r"^(\w{5,})\b.{3,60}?\s(?=\1\b)", x)  # "Anthem BlueCross and BlueShield Anthem Silver ..."
    if m and m.group(1).lower() not in _COMMON_WORDS:
        x = x[m.end() :]
    x = re.sub(r"\s+", " ", x).strip(" :|-–")
    return x or name


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
    d = build(picture_rows(layout.md), **kw)
    source = "md"
    if _nbad(d) >= 3:
        try:
            d2 = build(layout.pdf_rows, **kw)
            if _nbad(d2) < _nbad(d):
                d, source = d2, "pdf"
        except Exception as e:  # the table view is a second chance; keep the markdown result
            warnings.append(f"table view failed: {type(e).__name__}")
    elif _nbad(d) > 0:
        try:
            _fill_missing_rows(d, build(layout.pdf_rows, **kw))
        except Exception as e:
            warnings.append(f"table view failed: {type(e).__name__}")
    _dashfix(d, layout.md)
    label = _clean(d)
    label["plan_name"] = clean_plan_name(label["plan_name"])
    ext = normalize_v14(SBCExtraction.model_validate(label))
    missing = sum(v["in_network"] is None for v in d["services"].values())
    return ParseResult(extraction=ext, raw=d, source=source, missing_services=missing, warnings=warnings)
