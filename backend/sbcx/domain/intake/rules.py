"""Which yearly counts a quoted phrase supports (validator rule 3). The set is deliberately generous: it
checks that a count is grounded in the user's words, not that it is the only reading of them."""

from __future__ import annotations

import re

from sbcx.domain.explain.grounding import WORDS

# fixed phrases -> times a year (longest first so "every other week" wins over "week")
FREQUENCIES: list[tuple[str, int]] = [
    (r"every other week|bi-?weekly|every (2|two) weeks", 26),
    (r"twice a month|two times a month|2 times a month|semi-?monthly", 24),
    (r"every other month|every (2|two) months", 6),
    (r"every (3|three) months|quarterly|once a quarter", 4),
    (r"every (6|six) months|twice a year|two times a year|2 times a year|semi-?annual(ly)?", 2),
    (r"daily|every day|each day|once a day", 365),
    (r"weekly|every week|each week|once a week|a week|per week", 52),
    (r"monthly|every month|each month|once a month|a month|per month", 12),
    (r"yearly|annually|once a year|every year|each year|a year|per year", 1),
]
FREQ = [(re.compile(rf"(?i)\b(?:{rx})\b"), n) for rx, n in FREQUENCIES]

# "N times a week" style: the period's multiplier
PERIODS = [
    (re.compile(r"(?i)\b(a|per|each|every|/)\s*day\b"), 365),
    (re.compile(r"(?i)\b(a|per|each|every|/)\s*week\b|\bweekly\b"), 52),
    (re.compile(r"(?i)\b(a|per|each|every|/)\s*month\b|\bmonthly\b"), 12),
    (re.compile(r"(?i)\b(a|per|each|every|/)\s*quarter\b|\bquarterly\b"), 4),
]
_SUPPLY = re.compile(r"(?i)\b(\d{2,3})[- ]day (supply|supplies|prescription|refill)")
_NUM = re.compile(r"(?i)\b(\d{1,3})\b|\b(" + "|".join(WORDS) + r")\b|\b(once|twice)\b")


def numbers(quote: str) -> set[int]:
    out = set()
    for m in _NUM.finditer(quote):
        if m.group(1):
            out.add(int(m.group(1)))
        elif m.group(2):
            out.add(WORDS[m.group(2).lower()])
        else:
            out.add(1 if m.group(3).lower() == "once" else 2)
    return {n for n in out if n > 0}


def allowed_counts(quote: str) -> set[int]:
    """Counts a quote supports: a number in it, a frequency phrase, a number times the period it names, a product of
    two numbers in it, or 1."""
    nums = numbers(quote)
    freqs = {n for rx, n in FREQ if rx.search(quote)}
    periods = {n for rx, n in PERIODS if rx.search(quote)}
    out = nums | freqs | {n * p for n in nums for p in periods}
    out |= {a * b for a in nums for b in nums if a != b}  # "twice a week for 8 weeks" = 16
    for m in _SUPPLY.finditer(quote):  # "a 90-day supply": 3 fills of 30 days, or 12 for a year of them
        out |= {max(1, int(m.group(1)) // 30), 12}
    out.add(1)  # one stated occurrence ("a 3 day hospital stay" is one stay)
    return {n for n in out if 1 <= n <= 365}


# fill events need the user to have said which kind of drug it is (prompt rule, enforced here)
TIER_WORDS = {
    "generic_drug_fill": re.compile(r"(?i)\bgener\w*"),
    "brand_drug_fill": re.compile(r"(?i)(?<!non-)(?<!non )\b(preferred )?brand"),
    "nonpreferred_drug_fill": re.compile(r"(?i)\bnon-? ?preferred"),
    "specialty_drug_fill": re.compile(r"(?i)\bspecialty"),
}
