"""Rules added after the 200-document accuracy audit (eval/audits/2026-10-27-random200.md)."""

import pytest

from sbcx.domain.parse.build import spans_both, tier_prices_split
from sbcx.domain.parse.costs import cost
from sbcx.domain.parse.pipeline import clean_plan_name, picture_rows
from sbcx.domain.parse.questions import indfam, qrow, split_net


@pytest.mark.parametrize(
    "raw, copay, pct, ded",
    [
        ("$30 copay for the first three visits and 20% coinsurance thereafter", None, 20.0, None),
        ("$25 copay for the first four and 15% coinsurance thereafter", None, 15.0, None),
        (
            "First two visits: $1 copay / visit, deductible does not apply. Additional visits: $30 copay / visit, deductible does not apply.",
            30.0,
            None,
            False,
        ),
        (
            "$5 copay/first 3 in person or virtual visits (combined with MH/SUD), then $15 copay/office visit; $10 copay/virtual care visit",
            15.0,
            None,
            None,
        ),
        (
            "$5 copay / upfront office visit, deductible does not apply; $40 copay / additional office visit (after upfront limit), deductible does not apply",
            40.0,
            None,
            False,
        ),
        ("$30 copay for initial visit, then $0 copay. Deductible does not apply.", 0.0, 0.0, False),
        ("Reimbursed first $100, then 50% of covered charges; deductible does not apply", None, 50.0, False),
        # unchanged behavior
        ("$250 copay then 20% coinsurance", 250.0, 20.0, None),
        ("Visits 1-3: $10 copay; Visits 4+: $40 copay", 40.0, None, None),
    ],
)
def test_later_charge_wordings(raw, copay, pct, ded):
    c = cost(raw)
    assert (c["copay"], c["coinsurance_pct"], c["deductible_applies"]) == (copay, pct, ded)


def test_first_visits_charge_kept_in_note():
    assert cost("$30 copay for the first three visits and 20% coinsurance thereafter")["note"].startswith(
        "$30 copay for the first"
    )


@pytest.mark.parametrize(
    "raw, ded",
    [
        (
            "Lab: $0 copay/test when referred by an Antidote virtual provider or $75 copay/test; deductible does not apply. X-ray: 40% coinsurance",
            False,
        ),
        (
            "$75 copay/office visit when referred or $150 copay/office visit. Deductible does not apply. All other services are subject to 40% coinsurance after deductible.",
            False,
        ),
        (
            "$85 copay/office visit, $75 copay/virtual care visit, No charge/virtual visit; deductible does not apply. 0% coinsurance for other outpatient services",
            False,
        ),
        ("$25 copay", None),
    ],
)
def test_deductible_statement_closing_first_group(raw, ded):
    assert cost(raw)["deductible_applies"] is ded


def test_after_deductible_not_cut_by_label_lookalike():
    c = cost(
        "$100 copay after Deductible/prescription (retail) $270 copay after Deductible/prescription (mail-order)",
        svc=False,
    )
    assert c["copay"] == 100.0 and c["deductible_applies"] is True


def test_question_answer_with_literal_pipe_and_group_family():
    md = "|**What is the overall**<br>**deductible?**|$6000 per person | $12000 per<br>group|Generally, you must pay…|\n"
    ans = qrow(md, r"overall\s*deductible")
    assert indfam(ans) == {"individual": 6000.0, "family": 12000.0}


def test_question_answer_started_in_previous_row():
    md = (
        "||Fornetwork provider<br>- $6,550 Individual||\n"
        "|**What is the out-of-pocket**<br>**limit for this plan?**|/$13,100family. For out-of-network<br>provider - $19,650 individual/$39,300 family.|The out-of-pocket limit…|\n"
    )
    ans = qrow(md, r"out.{0,4}of.{0,4}pocket\s*limit")
    i, o = split_net(ans)
    assert indfam(i) == {"individual": 6550.0, "family": 13100.0}
    assert indfam(o) == {"individual": 19650.0, "family": 39300.0}


def test_period_thousands_separator():
    assert indfam("For network provider - $6.000 Individual / $12,000 .") == {
        "individual": 6000.0,
        "family": 12000.0,
    }
    assert indfam("$12.50 copay")["individual"] == 12.5


def test_spanned_out_of_network_cell():
    ci = cost("25% coinsurance")
    assert spans_both("25% coinsurance", "", ci)
    assert not spans_both("25% coinsurance", "Not covered", ci)
    assert not spans_both("25% coinsurance", None, ci)  # no out-of-network column


def test_shared_price_tier_names_not_split():
    assert not tier_prices_split(["$10 / 30-day supply", "Not Covered"], 2)
    assert tier_prices_split(["$10 copay; $25 copay", "Not Covered"], 2)


def test_picture_text_rows():
    md = "<!-- Start of picture text -->What You Will Pay<br>Children’s dental check-up  Not Covered Not Covered None<br><!-- End of picture text -->"
    rows = [line for line in picture_rows(md).split("\n") if line.startswith("||")]
    assert rows == ["||Children’s dental check-up|Not Covered|Not Covered None||"]


@pytest.mark.parametrize(
    "raw, clean",
    [
        ("Sanford Individual TRUE $1,750 | South Dakota", "Sanford Individual TRUE $1,750"),
        ("Portfolio Bronze | Plan Type HSA-eligible HMO", "Portfolio Bronze"),
        ("(domiciled in Utah) Bronze 8000", "Bronze 8000"),
        ("Wellpoint Wellpoint Essential Silver POS 6000", "Wellpoint Essential Silver POS 6000"),
        ("Anthem BlueCross and BlueShield Anthem Silver Pathway", "Anthem Silver Pathway"),
        ("Blue Cross Blue Shield Blue Advantage", "Blue Cross Blue Shield Blue Advantage"),
        ("Core Gold 1500", "Core Gold 1500"),
    ],
)
def test_plan_name_cleanup(raw, clean):
    assert clean_plan_name(raw) == clean
