"""Deductible and coverage claim checks C1-C5 (v2.1 T1.6) on the F1 fixture: A = Moda Bronze (visits and
drugs before the deductible, no children's dental), B = Anthem Catastrophic (deductible applies to
everything but preventive care and the first 3 primary care visits; covers children's dental)."""

import pytest

from sbcx.domain.explain.claims import deductible_claims
from sbcx.domain.explain.generate import explain, factsheet
from sbcx.domain.explanation import Explanation, ExplanationRecord
from tests.fixtures import f1, f1_compare
from tests.unit.test_engine_explain import run

R = f1_compare()
FACTS = factsheet(R)


def flags(*sentences: str) -> list[str]:
    e = Explanation(headline="h", key_points=list(sentences), scenarios=[], disclaimer="d")
    return deductible_claims(e, R, FACTS)


@pytest.mark.parametrize(
    "sentence,rule",
    [
        ("Plan A: you pay full cost until the deductible is met.", "C1"),
        ("Plan B covers specialist visits before the deductible.", "C2"),
        ("Plan B's generic drugs are not subject to the deductible.", "C2"),
        ("Plan A charges specialist visits after the deductible.", "C3"),
        ("Plan B does not cover children's dental check-ups.", "C4"),
        ("Plan A covers children's dental check-ups.", "C5"),
    ],
)
def test_false_claims_are_flagged(sentence, rule):
    got = flags(sentence)
    assert len(got) == 1 and got[0].startswith(f"[{rule}]"), got


@pytest.mark.parametrize(
    "sentence",
    [
        "Plan B: you pay full cost until the deductible is met.",
        "Plan A: you pay full price until the deductible, except for visits and drugs.",
        "Plan A covers specialist visits before the deductible.",
        "Plan B covers specialist visits after the deductible.",
        "Plan A does not cover children's dental check-ups.",
        "Plan B covers children's dental check-ups.",
        "Plan B covers primary care visits before the deductible.",  # first 3 visits: federal rule
        "Plan B: the deductible applies to everything except preventive care.",
    ],
)
def test_true_claims_pass(sentence):
    assert flags(sentence) == []


def test_hedged_sentences_are_not_claims():
    assert flags("Plan B may cover specialist visits before the deductible.") == []


def test_multi_plan_sentences_attribute_each_service_to_the_nearest_plan():
    assert (
        flags(
            "Plan A covers specialist visits before the deductible; Plan B covers them after the deductible."
        )
        == []
    )
    got = flags(
        "Plan A covers generic drugs before the deductible, while Plan B covers specialist visits before the deductible."
    )
    assert len(got) == 1 and "Plan B" in got[0] and "Specialist visit" in got[0]


def test_services_without_an_unambiguous_alias_are_skipped():
    assert flags("Plan B covers hospital stays before the deductible.") == []


def test_f2_sentence_from_the_served_explanation_is_rejected():
    stored = ExplanationRecord.model_validate(f1()["explanation"]).content
    got = deductible_claims(stored, R, FACTS)
    assert len(got) == 1 and got[0].startswith("[C1]") and "pay full cost until the deductible" in got[0]


@pytest.mark.parametrize("result", [R, run()], ids=["f1", "worked_example"])
def test_template_explanation_passes_every_check(result):
    rec = explain(result, None, "m")
    assert rec.source == "template" and rec.grounding.ok, rec.grounding


def test_factsheet_v3_deductible_facts():
    plans = {p["key"]: p for p in FACTS["plans"]}
    a, b = plans["A"], plans["B"]
    assert {"Primary care visit", "Specialist visit", "Urgent care", "Generic drugs"} <= set(
        a["covered_before_deductible"]
    )
    assert not a["deductible_applies_to_everything_else"]
    assert set(b["covered_before_deductible"]) == {
        "Primary care visit (first 3 visits)",
        "Preventive care / screening",
    }
    assert b["deductible_applies_to_everything_else"]
    top = FACTS["top_differences"][0]
    per = next(iter(top["per_plan"].values()))
    assert "cost_per_use_after_deductible" in per and "cost_per_use_before_deductible" in per
    assert "overall_verdict" in top


def test_a_deductible_phrase_applies_only_to_the_services_next_to_it():
    """Live check 2026-10-29: "...specialist visits ($85) and emergency room care (40% coinsurance after deductible)"
    was blamed on specialist visits."""
    assert (
        flags("Plan A has copays for specialist visits ($120) and imaging (no charge after deductible).")
        == []
    )
    got = flags("Plan A charges specialist visits, urgent care, or generic drugs after the deductible.")
    assert len(got) == 3 and all(g.startswith("[C3]") for g in got)


def test_not_covered_before_the_deductible_is_a_timing_claim():
    """Live check 2026-10-29: "does not cover X before the deductible is met; you pay full cost until then" was read
    as a coverage claim (C4) and an exemption claim (C2), which forced a template explanation."""
    assert (
        flags(
            "Plan B does not cover specialist visits, urgent care, or generic drugs before the deductible is met."
        )
        == []
    )
    got = flags("Plan A does not cover specialist visits or urgent care before the deductible is met.")
    assert len(got) == 2 and all(g.startswith("[C3]") for g in got)


def test_before_and_after_and_timing_phrases_are_not_claims():
    """Live check 2026-10-29: correct sentences that describe cost before and after the deductible."""
    assert flags("For specialist visits, Plan A charges a $120 copay before and after the deductible.") == []
    assert flags("Plan B charges $250 for specialist visits before the deductible and $0 after.") == []
    got = flags("Plan B covers specialist visits before the deductible.")
    assert len(got) == 1 and got[0].startswith("[C2]")


def test_deductible_claims_need_the_sbc_to_say_so():
    """Live check 2026-10-29: "Imperial Preferred Gold does not cover specialist visits before the deductible" was
    served for a cell whose deductible is not stated."""
    r = run()
    facts = factsheet(r)
    e = Explanation(
        headline="h",
        key_points=[
            "Plan A does not cover imaging before the deductible.",
            "Plan A covers imaging after the deductible.",
        ],
        scenarios=[],
        disclaimer="d",
    )
    got = deductible_claims(e, r, facts)
    assert len(got) == 2 and all(g.startswith("[C3]") and "deductible not stated" in g for g in got)


def test_not_stated_wording_is_not_a_claim():
    assert flags("Plans A and B do not state whether the deductible applies to imaging or urgent care.") == []


def test_everything_else_needs_every_deductible_to_be_stated():
    """Live check 2026-10-29: a plan whose SBC leaves most deductibles unstated was described as "deductible applies
    to everything else"."""
    r = run()  # plan A leaves several deductibles unstated
    plans = {p["key"]: p for p in factsheet(r)["plans"]}
    assert plans["A"]["deductible_applies_to_everything_else"] is False
