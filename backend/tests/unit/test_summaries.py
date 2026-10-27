import pytest

from sbcx.domain.enrich.sections import SECTION_BY_ID, SECTIONS
from sbcx.domain.enrich.summarize import summarize, summarize_section
from sbcx.domain.explain.grounding import check, collect, extract_numbers
from sbcx.infra.llm.base import LLMError
from sbcx.infra.llm.fake import FakeLLMClient
from tests.unit.test_fallback import doc_with

SEC = SECTION_BY_ID["office_visits"]


def doc():
    return doc_with("$25 copay", 0.9)  # every service: $25 copay in network


def test_grounded_llm_summary_is_used():
    f = FakeLLMClient(
        {"section_summary": [{"summary": "Primary care costs $25 per visit.", "highlights": ["$25 copay"]}]}
    )
    s = summarize_section(doc(), SEC, f, "m")
    assert s.source == "llm" and "$25" in s.summary


def test_retry_after_ungrounded_numbers():
    f = FakeLLMClient(
        {
            "section_summary": [
                {"summary": "Visits cost $30.", "highlights": []},
                {"summary": "Visits cost $25.", "highlights": []},
            ]
        }
    )
    s = summarize_section(doc(), SEC, f, "m")
    assert s.source == "llm_retry"
    assert "$30" in f.calls[1]["user"]  # the retry names the bad number


def test_template_after_two_failures():
    f = FakeLLMClient(
        {"section_summary": [{"summary": "$30", "highlights": []}, {"summary": "$40", "highlights": []}]}
    )
    s = summarize_section(doc(), SEC, f, "m")
    assert s.source == "template" and "$25 copay" in s.summary


def test_template_when_llm_down_or_off():
    assert (
        summarize_section(doc(), SEC, FakeLLMClient({"section_summary": [LLMError("x")]}), "m").source
        == "template"
    )
    assert summarize_section(doc(), SEC, None, "m").source == "template"


def test_all_sections_and_templates_grounded():
    from sbcx.domain.enrich.sections import section_input, template_summary

    d = doc()
    out = summarize(d, None, "m")
    assert [s.section for s in out] == [s.id for s in SECTIONS]
    for sec in SECTIONS:
        text, _ = template_summary(d, sec)
        _, bad = check([text], collect(section_input(d, sec)))
        assert not bad, (sec.id, bad)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("$1,500 deductible", [("money", 1500.0)]),
        ("20% coinsurance", [("pct", 20.0)]),
        ("3 visits", [("num", 3.0)]),
        ("$2.5k", [("money", 2500.0)]),
        ("forty percent", []),
        ("twenty visits", [("num", 20.0)]),
    ],
)
def test_extract_numbers(text, expected):
    assert [(f.kind, f.value) for f in extract_numbers(text)] == expected


def test_check_flags_unknown_money_but_allows_small_counts():
    allowed = collect({"a": 25, "b": "limit 30 visits"})
    n, bad = check(["$25 copay, 30 visits, 2 plans, $26 total"], allowed)
    assert bad == ["$26"] and n == 4
