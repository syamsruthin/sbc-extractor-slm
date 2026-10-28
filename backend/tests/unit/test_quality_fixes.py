"""Fixes from the end-to-end comparison quality review (eval/audits/2026-10-28-e2e-comparison-quality.md)."""

from sbcx.domain.compare.cost_model import DeductibleHints, deductible_status
from sbcx.domain.display import describe_cost
from sbcx.domain.explain.generate import claim_check, factsheet, rankings
from sbcx.domain.explanation import Explanation
from sbcx.domain.parse.build import plan_name
from sbcx.domain.sbc import CostShare
from tests.unit.test_engine_explain import run

FREE = CostShare(covered=True, copay=0, coinsurance_pct=0, deductible_applies=None, note=None)


def test_deductible_status_never_hides_unknowns():
    assert deductible_status(FREE, "hospital_facility_fee", None, True) == "not_stated"
    assert describe_cost(FREE, status="not_stated") == "No charge, deductible not stated"
    assert (
        deductible_status(FREE, "hospital_facility_fee", DeductibleHints(unmarked_apply=True), True)
        == "applies_per_sbc"
    )
    assert (
        describe_cost(FREE, status="applies_per_sbc") == "No charge, after deductible (per the SBC's page 1)"
    )
    assert deductible_status(FREE, "preventive_care", None, True) == "before_per_sbc"
    assert deductible_status(FREE, "hospital_facility_fee", None, False) == "none"  # plan has no deductible


def test_comparison_cells_carry_status():
    r = run()
    img = next(s for s in r.services if s.service_key == "imaging")
    assert (
        img.cells["A"].deductible_status == "not_stated" and "deductible not stated" in img.cells["A"].display
    )
    assert img.cells["B"].deductible_status == "applies"


def test_rankings_and_claim_check():
    r = run()
    facts = factsheet(r)
    names = {p["key"]: p["name"] for p in facts["plans"]}
    assert facts["rankings"]["annual_premium"]["lowest_keys"] == ["B"] and names["B"]
    assert facts["rankings"]["worst_case_max_out_of_pocket"]["lowest_keys"] == ["B"]

    def exp(*points, scen=None):
        return Explanation(
            headline="Two plans compared.",
            key_points=list(points) or ["x"],
            scenarios=scen or [],
            watch_out=[],
            assumptions=[],
            disclaimer="d",
        )

    good = exp(
        "Plan B has the lowest annual premium.",
        "Plan A has the highest worst-case total.",
        "Plan B has the lowest annual premium, but the highest deductible.",  # two superlatives, two metrics
    )
    assert claim_check(good, facts) == []
    bad = exp("Plan A has the lowest worst-case total of $15,300, while Plan B is $11,060.")
    assert len(claim_check(bad, facts)) == 1
    # scenario: moderate use ranges overlap, so no single plan may be called lowest
    from sbcx.domain.explanation import ScenarioText

    overlap = exp(scen=[ScenarioText(scenario="Moderate use", text="Plan B has the lowest total cost.")])
    assert "overlap" in claim_check(overlap, facts)[0]
    hedged = exp(
        scen=[
            ScenarioText(
                scenario="Moderate use",
                text="The lowest cost depends on actual costs because Plan B's total ranges widely, overlapping Plan A.",
            )
        ]
    )
    assert claim_check(hedged, facts) == []  # hedged wording is what we want, not a claim
    low_ok = exp(scen=[ScenarioText(scenario="Low use", text="Plan B has the lowest total cost.")])
    assert claim_check(low_ok, facts) == []


def test_rankings_ties_and_missing():
    r = rankings({"annual_premium": {"A": 100, "B": 100, "C": None}}, {"A": "a", "B": "b", "C": "c"})
    assert r["annual_premium"]["lowest"] == ["a", "b"] and r["annual_premium"]["lowest_keys"] == ["A", "B"]
    assert rankings({"deductible": {"A": None, "B": 5}}, {"A": "a", "B": "b"}) == {}


def test_plan_name_kept_when_rest_is_coverage_words():
    rest = ". Harbor Health: Harbor Health S1 : Individual and Family ndividual and Family"
    assert plan_name(rest, "Harbor Health").startswith("Harbor Health S1")
