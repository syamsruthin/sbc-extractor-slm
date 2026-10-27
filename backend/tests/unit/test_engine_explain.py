from sbcx.domain.compare.engine import PlanInput, compare
from sbcx.domain.comparison import ComparisonRequest, PlanInputs, Verdict
from sbcx.domain.explain.generate import DISCLAIMER, _validate, explain, factsheet, template_explanation
from sbcx.infra.llm.base import LLMError
from sbcx.infra.llm.fake import FakeLLMClient
from tests.unit.test_cost_model import CFG, PLAN_A, PLAN_B, PRICES


def run(**kw):
    req = ComparisonRequest(
        document_ids=["a", "b"],
        inputs={
            "a": PlanInputs(monthly_premium=500),
            "b": PlanInputs(monthly_premium=380, employer_hsa_hra_annual=500),
        },
        scenario_ids=["low", "moderate"],
        **kw,
    )
    return compare([PlanInput("a", PLAN_A), PlanInput("b", PLAN_B)], req, CFG, PRICES)


def test_headline_and_worked_example_scenario():
    r = run()
    h = r.headline
    assert h.best_case == {"A": 6000.0, "B": 4060.0} and h.best_case_delta == {"B": -1940.0}
    assert h.worst_case == {"A": 15300.0, "B": 11060.0} and h.worst_case_delta == {"B": -4240.0}
    mod = next(s for s in r.scenarios if s.scenario.id == "moderate")
    assert (mod.per_plan["A"].total.low, mod.per_plan["A"].total.high) == (6848.0, 7840.0)
    assert mod.per_plan["B"].total.low == 7310.0
    assert (mod.delta_vs_base["B"].low, mod.delta_vs_base["B"].high) == (-530.0, 462.0)
    assert mod.ranges_overlap and set(mod.cheapest) == {"A", "B"}
    low = next(s for s in r.scenarios if s.scenario.id == "low")
    assert low.cheapest == ["B"] and not low.ranges_overlap


def test_service_verdicts():
    r = run()
    spec = next(s for s in r.services if s.service_key == "specialist_visit")
    # A: $50 copay; B: 20% of $250 = $50 once the deductible is met -> same per use, estimated comparison
    assert spec.cells["A"].est_cost_per_use == 50 and spec.cells["B"].est_cost_per_use == 50
    assert spec.verdicts["B"] == Verdict.same and spec.comparison_kind == "estimated"
    assert "deductible_difference" in spec.flags
    pcp = next(s for s in r.services if s.service_key == "primary_care_visit")
    assert pcp.verdicts["B"] == Verdict.worse and pcp.delta_per_use["B"] == 30.0 - 25.0  # 20% of $150 vs $25


def test_deterministic_hash():
    assert run().result_hash == run().result_hash
    assert run(reference_price_overrides={"imaging": 2000}).result_hash != run().result_hash


def test_ranking_puts_big_items_first():
    r = run()
    assert r.ranked and r.ranked[0].impact_usd >= r.ranked[-1].impact_usd


def test_template_explanation_is_grounded():
    r = run()
    facts = factsheet(r)
    e = template_explanation(facts)
    rep = _validate(e, facts)
    assert rep.ok, rep
    mod = next(s for s in e.scenarios if s.scenario == "Moderate use")
    assert "depends" in mod.text  # overlapping ranges are not called a win


def _good(facts):
    return {
        "headline": "Plan B has lower premiums.",
        "key_points": ["Plan B premiums are $4,560 a year."],
        "scenarios": [{"scenario": "Low use", "text": "Plan B totals $4,480."}],
        "watch_out": [],
        "assumptions": [],
        "disclaimer": "x",
    }


def test_llm_path_retry_and_template():
    r = run()
    facts = factsheet(r)
    ok = explain(r, FakeLLMClient({"explanation": [_good(facts)]}), "m")
    assert ok.source == "llm" and ok.grounding.ok and ok.content.disclaimer == DISCLAIMER

    bad = dict(_good(facts), headline="You should choose Plan B to save $999.")
    f = FakeLLMClient({"explanation": [bad, _good(facts)]})
    retry = explain(r, f, "m")
    assert retry.source == "llm_retry"
    assert "$999" in f.calls[1]["user"] and "you should" in f.calls[1]["user"].lower()

    tpl = explain(r, FakeLLMClient({"explanation": [bad, bad]}), "m")
    assert tpl.source == "template" and tpl.grounding.ok
    assert explain(r, FakeLLMClient({"explanation": [LLMError("down")]}), "m").source == "template"
    assert explain(r, None, "m").source == "template"
