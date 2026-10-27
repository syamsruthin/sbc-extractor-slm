"""Cell rules. Hand-written cases cover the labeling conventions (guideline v1.2 + v1.4 README);
tests/cases/cells.jsonl holds cells mined from the reviewed v1.4 labels (see tests/mine_cells.py)."""

import json
from pathlib import Path

import pytest

from sbcx.domain.parse.cells import ded_flag
from sbcx.domain.parse.costs import cat, cost

NC = {"covered": False, "copay": None, "coinsurance_pct": None, "deductible_applies": None, "note": None}


def cs(copay=None, pct=None, ded=None, note=None):
    return {"covered": True, "copay": copay, "coinsurance_pct": pct, "deductible_applies": ded, "note": note}


CONVENTIONS = [
    ("No charge", cs(0.0, 0.0)),
    ("$0 copay", cs(0.0, 0.0)),
    ("Not covered", NC),
    ("Not Covered", NC),
    ("20% coinsurance", cs(pct=20.0)),
    ("0% coinsurance", cs(pct=0.0)),  # 0% coinsurance is not a $0 copay
    ("$25 copay/visit, deductible does not apply", cs(25.0, ded=False)),
    ("40% coinsurance after deductible", cs(pct=40.0, ded=True)),
    ("$250 copay then 20% coinsurance", cs(250.0, 20.0)),  # one combined charge fills both
    # different parts: first listed part in the fields, the rest in the note
    (
        "$300 Preferred Brand; 40% coinsurance Non-Preferred Brand",
        cs(300.0, note="40% coinsurance Non-Preferred Brand."),
    ),
    # first visits / later visits: the later charge is the structured value
    ("First 3 visits $5 copay, then $25 copay", cs(25.0, note="First 3 visits $5 copay.")),
    ("Visits 1-3: $10 copay; Visits 4+: $40 copay", cs(40.0, note="Visits 1-3: $10 copay.")),
    ("Visit 1: $35; Visit 2 and after: No charge", cs(0.0, 0.0, note="Visit 1: $35.")),
    (
        "First three visits $5 co-pay/visit, deductible does not apply. Subsequent visits, $25 co-pay/visit, deductible does not apply.",
        cs(25.0, ded=False, note="First three visits $5 co-pay/visit, deductible does not apply."),
    ),
]


@pytest.mark.parametrize("raw, expected", CONVENTIONS)
def test_conventions(raw, expected):
    assert cost(raw) == expected


@pytest.mark.parametrize(
    "text, flag",
    [
        ("deductible does not apply", False),
        ("Deductible waived", False),
        ("not subject to the deductible", False),
        ("after deductible", True),
        ("subject to deductible", True),
        ("$40 copay", None),
    ],
)
def test_ded_flag(text, flag):
    assert ded_flag(text) is flag


def test_limitations_never_set_price():
    c = cost("$30 copay", "Coinsurance 50% for other outpatient services")
    assert c["copay"] == 30.0 and c["coinsurance_pct"] is None


@pytest.mark.parametrize(
    "name, category",
    [
        ("Generic drugs - Tier 1", "generic"),
        ("Preferred brand drugs", "preferred_brand"),
        ("Non-preferred brand drugs", "non_preferred_brand"),
        ("Specialty drugs- Tier 4", "specialty"),
        ("Tier 2", "other"),  # category comes from the label words only
    ],
)
def test_drug_category(name, category):
    assert cat(name) == category


CASES = Path(__file__).resolve().parents[1] / "cases" / "cells.jsonl"
MINED = [json.loads(line) for line in CASES.read_text().splitlines()] if CASES.exists() else []


@pytest.mark.skipif(not MINED, reason="no mined cases")
@pytest.mark.parametrize("case", MINED, ids=lambda c: c["id"])
def test_mined_cells(case):
    got = cost(case["text"], case.get("lim"), svc=case.get("svc", True), noteless=case.get("noteless", False))
    exp = case["expected"]
    if got is None or exp is None:
        assert got == exp
        return
    for k in ("covered", "copay", "coinsurance_pct", "deductible_applies"):
        assert got[k] == exp[k], k


def test_zero_coinsurance_keeps_copay_null_through_pipeline_normalization():
    """Regression: the v1.2-era schema.normalize() turned "0% coinsurance" into copay 0."""
    from sbcx.domain.parse.pipeline import normalize_v14
    from tests.unit.test_fallback import doc_with

    d = doc_with("0% coinsurance", 0.9, cs(pct=0.0))
    normalize_v14(d.benefits)
    c = d.benefits.services.imaging.in_network
    assert c.copay is None and c.coinsurance_pct == 0.0
