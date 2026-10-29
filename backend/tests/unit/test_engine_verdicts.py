"""Engine 1.3.0: cost per use before the deductible and the combined verdict (v2.1 T1.1)."""

import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sbcx.domain.compare.cost_model import DeductibleHints
from sbcx.domain.compare.engine import est_before_deductible, est_per_use, overall_verdict, range_verdict
from sbcx.domain.comparison import Money, OverallVerdict, Verdict
from sbcx.domain.sbc import CostShare
from tests.fixtures import f1_compare

V, OV = Verdict, OverallVerdict


@pytest.mark.parametrize(
    "base,other,expected",
    [
        ((100, 100), (50, 50), V.better),
        ((100, 100), (150, 150), V.worse),
        ((100, 100), (100.5, 100.5), V.same),
        ((100, 200), (150, 150), V.not_comparable),  # ranges overlap
        ((0, 300), (0, 300), V.same),
    ],
)
def test_range_verdict(base, other, expected):
    assert (
        range_verdict(Money(low=base[0], high=base[1]), Money(low=other[0], high=other[1]), 250) == expected
    )


def test_range_verdict_missing():
    assert range_verdict(None, Money(low=1, high=1), 100) == V.not_comparable


def test_overall_verdict_every_combination():
    expected = {
        (V.better, V.better): OV.better,
        (V.worse, V.worse): OV.worse,
        (V.same, V.same): OV.same,
        (V.not_comparable, V.not_comparable): OV.not_comparable,
        (V.better, V.same): OV.better,
        (V.same, V.better): OV.better,
        (V.worse, V.same): OV.worse,
        (V.same, V.worse): OV.worse,
    }
    for after, before in itertools.product(V, V):
        want = expected.get((after, before), OV.depends_on_deductible)
        assert overall_verdict(after, before) == want, (after, before)


def cs(copay=None, coinsurance_pct=None, deductible_applies=None, covered=True) -> CostShare:
    return CostShare(
        covered=covered,
        copay=copay,
        coinsurance_pct=coinsurance_pct,
        deductible_applies=deductible_applies,
        note=None,
    )


def test_before_deductible_by_status():
    # deductible applies (row says so): full price up to the deductible
    assert est_before_deductible(
        cs(coinsurance_pct=20, deductible_applies=True), "imaging", 1000, None, 500
    ) == Money(low=600, high=600)  # 500 to the deductible + 20% of the remaining 500
    # deductible doesn't apply: the copay
    assert est_before_deductible(
        cs(copay=40, deductible_applies=False), "specialist_visit", 250, None, 3000
    ) == Money(low=40, high=40)
    # not stated: a range (low: copay only, high: full price)
    assert est_before_deductible(cs(copay=40), "specialist_visit", 250, None, 3000) == Money(low=40, high=250)
    # page-1 evidence: unmarked rows apply the deductible
    hints = DeductibleHints(unmarked_apply=True, reason="hsa")
    assert est_before_deductible(cs(copay=40), "specialist_visit", 250, hints, 3000) == Money(
        low=250, high=250
    )
    # catastrophic: the first primary care visit comes before the deductible
    cat = DeductibleHints(True, frozenset(), "catastrophic", pcp_visits_before=3)
    assert est_before_deductible(cs(coinsurance_pct=0), "primary_care_visit", 150, cat, 9000) == Money(
        low=0, high=0
    )
    # no deductible: same as after
    assert est_before_deductible(cs(copay=40), "specialist_visit", 250, None, 0) == Money(low=40, high=40)
    # not covered: full price; unknown cell: no estimate
    assert est_before_deductible(cs(covered=False), "specialist_visit", 250, None, 3000) == Money(
        low=250, high=250
    )
    assert est_before_deductible(None, "specialist_visit", 250, None, 3000) is None


@given(
    copay=st.one_of(st.none(), st.floats(0, 500)),
    pct=st.one_of(st.none(), st.floats(0, 100)),
    applies=st.one_of(st.none(), st.booleans()),
    allowed=st.floats(1, 10_000),
    ded=st.floats(0, 20_000),
)
def test_before_is_a_range_and_never_below_after(copay, pct, applies, allowed, ded):
    c = cs(copay=copay, coinsurance_pct=pct, deductible_applies=applies)
    b = est_before_deductible(c, "specialist_visit", allowed, None, ded)
    after = est_per_use(c, allowed)
    if b is None:
        assert copay is None and pct is None
        return
    assert b.low <= b.high
    if ded >= allowed and after is not None:
        assert b.high >= after - 0.01


def test_f1_catastrophic_rows_depend_on_deductible():
    """Discovery F1: Anthem Catastrophic (B) looked 'lower cost' on every row because per-use costs assumed the
    $10,600 deductible was met."""
    r = f1_compare()
    rows = {d.service_key: d for d in r.services} | {f"drug:{d.category}": d for d in r.drug_tiers}
    depends = [
        "specialist_visit",
        "urgent_care",
        "mental_health_outpatient",
        "rehabilitation",
        "habilitation",
        "drug:generic",
        "drug:preferred_brand",
        "drug:non_preferred_brand",
        "drug:specialty",
    ]
    for key in depends:
        assert rows[key].verdicts["B"] == V.better, key  # unchanged after-deductible verdict
        assert rows[key].overall_verdicts["B"] == OV.depends_on_deductible, key
    # the first primary care visits come before the deductible on a catastrophic plan
    assert rows["primary_care_visit"].overall_verdicts["B"] == OV.better
    assert rows["specialist_visit"].cells["B"].est_cost_before_deductible == Money(low=250, high=250)
    assert rows["specialist_visit"].cells["A"].est_cost_before_deductible == Money(low=120, high=120)
