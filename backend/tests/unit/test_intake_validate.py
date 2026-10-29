"""Usage intake: count rules and the validator (v2.1 T4.2)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sbcx.domain.intake.rules import allowed_counts
from sbcx.domain.intake.schema import DraftEvent, Unmodeled, UsageDraft
from sbcx.domain.intake.validate import validate

EVENTS = {
    "specialist_visit": {},
    "therapy_visit": {},
    "generic_drug_fill": {},
    "childbirth": {},
    "pt_visit": {},
}
TEXT = "I see a  Therapist every other week, 3 specialist visits, generic pills monthly. I'm having a baby. Dental cleanings."


def ev(event, count, quote, member=0):
    return DraftEvent(event=event, count=count, member=member, quote=quote, basis="")


@pytest.mark.parametrize(
    "quote,count",
    [
        ("every other week", 26),
        ("twice a month", 24),
        ("generic pills monthly", 12),
        ("3 specialist visits", 3),
        ("PT 3 times a week", 156),
        ("two visits", 2),
        ("I'm having a baby", 1),
        ("every 3 months", 4),
        ("twice a year", 2),
        ("90-day supply", 3),
        ("90-day supply of my statin", 12),
        ("twice a week for 8 weeks", 16),
    ],
)
def test_allowed_counts(quote, count):
    assert count in allowed_counts(quote)


def test_counts_need_words_that_support_them():
    assert 12 not in allowed_counts("3 specialist visits")
    assert 52 not in allowed_counts("I'm having a baby")
    assert 1 in allowed_counts("a 3 day hospital stay")  # one stay


def test_drug_fills_need_the_kind_of_drug():
    """Eval 2026-10-29: "I take Humira every two weeks" was entered as a specialty fill without the user saying so."""
    text = "I take Humira every two weeks, and a generic pill monthly."
    events = {"specialty_drug_fill": {}, "generic_drug_fill": {}}
    bad = validate(
        UsageDraft(events=[ev("specialty_drug_fill", 26, "Humira every two weeks")], unmodeled=[]),
        text,
        events,
        1,
    )
    assert bad.events == [] and "which kind of drug" in bad.violations[0]
    good = validate(
        UsageDraft(events=[ev("generic_drug_fill", 12, "a generic pill monthly")], unmodeled=[]),
        text,
        events,
        1,
    )
    assert good.violations == []


def test_valid_draft_passes_with_case_and_space_differences():
    d = UsageDraft(
        events=[
            ev("therapy_visit", 26, "see a therapist every other week"),
            ev("specialist_visit", 3, "3 specialist visits"),
            ev("generic_drug_fill", 12, "generic pills monthly"),
            ev("childbirth", 1, "having a baby"),
        ],
        unmodeled=[Unmodeled(quote="Dental cleanings", reason="adult dental not modeled")],
    )
    c = validate(d, TEXT, EVENTS, members=1)
    assert c.violations == [] and len(c.events) == 4 and len(c.unmodeled) == 1


@pytest.mark.parametrize(
    "event,why",
    [
        (ev("mri", 1, "3 specialist visits"), "unknown event"),
        (ev("specialist_visit", 3, "3 specialist visits", member=1), "member 1"),
        (ev("specialist_visit", 3, "4 specialist visits"), "not in the description"),
        (ev("specialist_visit", 12, "3 specialist visits"), "count 12"),
        (ev("specialist_visit", 0, "3 specialist visits"), "count 0"),
    ],
)
def test_each_rule(event, why):
    c = validate(UsageDraft(events=[event], unmodeled=[]), TEXT, EVENTS, members=1)
    assert len(c.violations) == 1 and why in c.violations[0] and c.events == []


def test_duplicates_merge():
    d = UsageDraft(
        events=[
            ev("specialist_visit", 3, "3 specialist visits"),
            ev("specialist_visit", 26, "every other week"),
        ],
        unmodeled=[],
    )
    c = validate(d, TEXT, EVENTS, members=1)
    assert [(e.event, e.count) for e in c.events] == [("specialist_visit", 29)]


def test_unmodeled_quotes_must_be_in_the_text():
    c = validate(UsageDraft(events=[], unmodeled=[Unmodeled(quote="glasses", reason="x")]), TEXT, EVENTS, 1)
    assert c.violations and not c.unmodeled


@given(quote=st.text(min_size=1, max_size=40))
def test_never_accepts_a_quote_absent_from_the_text(quote):
    if quote.strip().lower() in " ".join(TEXT.split()).lower():
        return
    c = validate(UsageDraft(events=[ev("specialist_visit", 1, quote)], unmodeled=[]), TEXT, EVENTS, members=1)
    assert c.events == []
