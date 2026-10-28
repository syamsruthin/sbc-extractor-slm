"""Cost engine: the worked example from docs/design/v2/06-cost-model.md §8, the cost-share formula,
family accumulators, and hypothesis invariants."""

from hypothesis import given, settings
from hypothesis import strategies as st

from sbcx.config import get_settings
from sbcx.domain.benefits import BenefitsDocument, BenefitsExtras, DeductibleType, Versions
from sbcx.domain.compare.config import ReferencePrices, load_scenarios
from sbcx.domain.compare.cost_model import member_pays, simulate
from sbcx.domain.comparison import CoverageTier, Event, PlanInputs, Scenario
from sbcx.domain.sbc import CostShare, SBCExtraction
from tests.unit.test_fallback import SVC

CFG = load_scenarios(str(get_settings().config_dir))
PRICES = ReferencePrices(
    "test",
    "test",
    {k: 100.0 for k in SVC}
    | {
        "preventive_care": 250,
        "primary_care_visit": 150,
        "specialist_visit": 250,
        "diagnostic_test": 120,
        "imaging": 1000,
        "urgent_care": 200,
    },
    {"generic": 30, "preferred_brand": 300, "non_preferred_brand": 500, "specialty": 4000},
)
MODERATE = CFG.preset("moderate")


def cs(copay=None, pct=None, ded=None, covered=True):
    return {
        "covered": covered,
        "copay": copay,
        "coinsurance_pct": pct,
        "deductible_applies": ded,
        "note": None,
    }


def plan(
    ded, oop, cells: dict, default, generic, ded_fam=None, oop_fam=None, dtype=DeductibleType.embedded
) -> BenefitsDocument:
    services = {k: {"in_network": cells.get(k, default), "out_of_network": None} for k in SVC}
    ext = SBCExtraction.model_validate(
        {
            "plan_name": "P",
            "issuer": "I",
            "plan_type": "PPO",
            "coverage_period": "01/01/2026 - 12/31/2026",
            "deductible": {"in_network": {"individual": ded, "family": ded_fam}, "out_of_network": None},
            "out_of_pocket_limit": {
                "in_network": {"individual": oop, "family": oop_fam},
                "out_of_network": None,
            },
            "services_before_deductible": [],
            "referral_required_for_specialist": None,
            "services": services,
            "drug_tiers": [
                {
                    "name": "Tier 1 Generic",
                    "category": "generic",
                    "retail": {"in_network": generic, "out_of_network": None},
                }
            ],
            "excluded_services": [],
        }
    )
    return BenefitsDocument(
        sha256="x",
        versions=Versions(schema_version="2", parser_version="2", guideline_version="1.4"),
        benefits=ext,
        extras=BenefitsExtras(deductible_type=dtype),
    )


# docs/design/v2/06-cost-model.md §8
PLAN_A = plan(
    1500,
    9300,
    {
        "preventive_care": cs(0, 0),
        "primary_care_visit": cs(25, ded=False),
        "specialist_visit": cs(50, ded=False),
        "diagnostic_test": cs(pct=20),
        "imaging": cs(pct=20),
        "urgent_care": cs(25, ded=False),
    },
    cs(pct=20),
    cs(25, ded=False),
)
PLAN_B = plan(3500, 7000, {"preventive_care": cs(0, 0, ded=False)}, cs(pct=20, ded=True), cs(10, ded=True))


def test_worked_example_plan_a_range():
    r = simulate(PLAN_A, PlanInputs(monthly_premium=500), MODERATE, CFG, PRICES)
    assert (r.out_of_pocket.low, r.out_of_pocket.high) == (848.0, 1840.0)
    assert (r.total.low, r.total.high) == (6848.0, 7840.0)
    assert any("deductible applies" in li.note for li in r.trace)


def test_worked_example_plan_b_exact():
    r = simulate(PLAN_B, PlanInputs(monthly_premium=380, employer_hsa_hra_annual=500), MODERATE, CFG, PRICES)
    assert r.out_of_pocket.low == r.out_of_pocket.high == 3250.0
    assert r.total.low == 7310.0 and not r.deductible_met


def test_cost_share_formula():
    A = 1000.0
    assert member_pays(_cs(copay=40), A, 0, "low").amount == 40
    assert member_pays(_cs(pct=20, ded=True), A, 300, "low").amount == 300 + 140
    assert member_pays(_cs(copay=250, pct=20), A, 0, "low").amount == 250 + 150
    assert member_pays(_cs(copay=40), 30, 0, "low").amount == 30  # copay never above the allowed amount
    nc = member_pays(_cs(covered=False), A, 0, "low")
    assert nc.amount == A and not nc.counts_toward_oop and nc.gap
    assert member_pays(_cs(), A, 0, "low").amount == 0 and member_pays(_cs(), A, 0, "high").amount == A
    # "No charge" with an unstated deductible is a range: SBC charts show costs after the deductible
    assert member_pays(_cs(copay=0, pct=0), A, 500, "low").amount == 0
    assert member_pays(_cs(copay=0, pct=0), A, 500, "high").amount == 500


def _cs(**kw):
    return CostShare(**cs(**kw))


def test_member_pays_accepts_models():
    assert member_pays(_cs(copay=10), 100, 0, "low").amount == 10


def test_oop_cap_hit_mid_claim():
    p = plan(1000, 1500, {}, cs(pct=50, ded=True), cs(10))
    sc = Scenario(id="c", label="c", events=[Event(event="hospital_stay", count=1)])
    prices = ReferencePrices("t", "t", {k: 10000.0 for k in SVC}, PRICES.drugs)
    r = simulate(p, PlanInputs(), sc, CFG, prices)
    assert r.out_of_pocket.high == 1500 and r.oop_limit_met


def test_family_embedded_vs_aggregate():
    sc = Scenario(id="f", label="f", events=[Event(event="mri", count=3, member=0)])
    prices = ReferencePrices("t", "t", {k: 1000.0 for k in SVC}, PRICES.drugs)
    args = (2000, 8000, {}, cs(pct=20, ded=True), cs(10))
    emb = simulate(
        plan(*args, ded_fam=4000, oop_fam=16000), PlanInputs(), sc, CFG, prices, CoverageTier.family
    )
    agg = simulate(
        plan(*args, ded_fam=4000, oop_fam=16000, dtype=DeductibleType.aggregate),
        PlanInputs(),
        sc,
        CFG,
        prices,
        CoverageTier.family,
    )
    # embedded: member 0 stops at the $2,000 individual deductible; aggregate: pays toward the $4,000 family one
    assert emb.out_of_pocket.low == 2000 + 0.2 * 1000
    assert agg.out_of_pocket.low == 3000
    unk = simulate(
        plan(*args, ded_fam=4000, oop_fam=16000, dtype=DeductibleType.unknown),
        PlanInputs(),
        sc,
        CFG,
        prices,
        CoverageTier.family,
    )
    assert (unk.out_of_pocket.low, unk.out_of_pocket.high) == (2200, 3000)


cells = st.builds(
    lambda kind, c, p, d: cs(
        *{"copay": (c, None), "pct": (None, p), "both": (c, p), "nc": (None, None)}[kind],
        ded=d,
        covered=kind != "nc",
    ),
    st.sampled_from(["copay", "pct", "both", "nc"]),
    st.integers(0, 500),
    st.integers(0, 100),
    st.sampled_from([True, False, None]),
)
scenarios = st.lists(
    st.tuples(st.sampled_from(sorted(CFG.event_types)), st.integers(1, 6)), min_size=1, max_size=6
)


@settings(max_examples=150, deadline=None)
@given(
    ded=st.integers(0, 8000),
    extra=st.integers(0, 10000),
    c=cells,
    generic=cells,
    evs=scenarios,
    prem=st.one_of(st.none(), st.integers(0, 1500)),
)
def test_invariants(ded, extra, c, generic, evs, prem):
    p = plan(ded, ded + extra, {}, c, generic)
    sc = Scenario(id="x", label="x", events=[Event(event=e, count=n) for e, n in evs])
    r = simulate(p, PlanInputs(monthly_premium=prem), sc, CFG, PRICES)
    assert r.out_of_pocket.low <= r.out_of_pocket.high + 1e-6
    for bound in ("low", "high"):
        paid = sum(getattr(li.member_pays, bound) for li in r.trace if not li.note.startswith("not covered"))
        assert paid <= ded + extra + 0.05  # covered care never exceeds the OOP limit
    again = simulate(p, PlanInputs(monthly_premium=prem), sc, CFG, PRICES)
    assert again.model_dump() == r.model_dump()  # deterministic
    more = Scenario(id="y", label="y", events=[*sc.events, Event(event="mri", count=1)])
    r2 = simulate(p, PlanInputs(monthly_premium=prem), more, CFG, PRICES)
    assert r2.out_of_pocket.high >= r.out_of_pocket.high - 1e-6  # adding care never lowers cost
    if ded == 0:
        assert (
            r.out_of_pocket.low == r.out_of_pocket.high or c["copay"] is None or c["coinsurance_pct"] is None
        )


@settings(max_examples=80, deadline=None)
@given(copay=st.integers(0, 300), bump=st.integers(1, 200), evs=scenarios)
def test_raising_copay_never_lowers_cost(copay, bump, evs):
    sc = Scenario(id="x", label="x", events=[Event(event=e, count=n) for e, n in evs])
    lo = simulate(
        plan(1000, 6000, {}, cs(copay, ded=False), cs(copay, ded=False)), PlanInputs(), sc, CFG, PRICES
    )
    hi = simulate(
        plan(1000, 6000, {}, cs(copay + bump, ded=False), cs(copay + bump, ded=False)),
        PlanInputs(),
        sc,
        CFG,
        PRICES,
    )
    assert hi.out_of_pocket.low >= lo.out_of_pocket.low - 1e-6


def test_deductible_evidence_rules():
    from sbcx.domain.compare.cost_model import DeductibleHints, resolve_applies

    free = _cs(copay=0, pct=0)
    assert (
        resolve_applies(free, "preventive_care", "high") is False
    )  # in-network preventive care is free by law
    assert resolve_applies(free, "hospital_facility_fee", "low") is False
    assert resolve_applies(free, "hospital_facility_fee", "high") is True
    marked = DeductibleHints(unmarked_apply=True)
    assert (
        resolve_applies(free, "hospital_facility_fee", "low", marked) is True
    )  # page-1 statement narrows the range
    named = DeductibleHints(before=frozenset({"primary_care_visit"}))
    assert resolve_applies(_cs(copay=25), "primary_care_visit", "high", named) is False
    assert (
        resolve_applies(_cs(copay=25, ded=True), "primary_care_visit", "low", named) is True
    )  # the row wins


def test_no_charge_after_deductible_plan():
    """Oregon-style bronze: deductible = OOP limit, chart cells say "No charge", and page 1 says only services
    marked 'deductible does not apply' are covered first. Heavy use must reach the OOP limit."""
    p = plan(9200, 9200, {"preventive_care": cs(0, 0)}, cs(0, 0), cs(0, 0))
    p.benefits.services_before_deductible = [
        'Certain preventive care and those services listed below as "deductible does not apply"'
    ]
    sc = Scenario(
        id="h",
        label="h",
        events=[Event(event="hospital_stay", count=1), Event(event="preventive_visit", count=1)],
    )
    r = simulate(p, PlanInputs(monthly_premium=500), sc, CFG, PRICES)
    assert (
        r.out_of_pocket.low == r.out_of_pocket.high == 200.0
    )  # PRICES: hospital fees 100 + 100 in the test table
    big = ReferencePrices("t", "t", {k: 10000.0 for k in SVC}, PRICES.drugs)
    r2 = simulate(p, PlanInputs(monthly_premium=500), sc, CFG, big)
    assert r2.out_of_pocket.low == r2.out_of_pocket.high == 9200.0 and r2.oop_limit_met
    assert any("marked 'deductible does not apply'" in a for a in r2.assumptions)
