"""Numeric grounding: every amount, percentage and count an LLM writes must appear in the data it
was given. Shared by section summaries and the comparison explanation."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "sixty": 60,
    "ninety": 90,
}
_NUM = re.compile(
    r"(?P<money>\$\s?\d[\d,]*(?:\.\d+)?\s?(?:k\b|K\b)?)"
    r"|(?P<pct>\d+(?:\.\d+)?\s?(?:%|percent\b))"
    r"|(?P<num>(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\d]))"
    r"|(?P<word>\b(?:" + "|".join(WORDS) + r")\b)",
    re.I,
)


@dataclass
class Found:
    kind: str  # money | pct | num
    value: float
    text: str


def extract_numbers(text: str) -> list[Found]:
    out = []
    for m in _NUM.finditer(text or ""):
        t = m.group(0)
        if m.group("money"):
            raw = t.replace("$", "").replace(",", "").strip()
            mult = 1000 if raw.lower().endswith("k") else 1
            out.append(Found("money", float(raw.rstrip("kK").strip()) * mult, t))
        elif m.group("pct"):
            out.append(Found("pct", float(re.sub(r"[^\d.]", "", t)), t))
        elif m.group("num"):
            out.append(Found("num", float(t.replace(",", "")), t))
        else:
            out.append(Found("num", float(WORDS[t.lower()]), t))
    return out


@dataclass
class AllowedNumbers:
    money: set[float] = field(default_factory=set)
    pct: set[float] = field(default_factory=set)
    nums: set[float] = field(default_factory=set)

    def add_value(self, v: float) -> None:
        v = round(float(v), 2)
        self.money.update({v, abs(v), round(abs(v))})
        self.pct.add(abs(v))
        self.nums.update({abs(v), round(abs(v))})

    def add_text(self, text: str) -> None:
        for f in extract_numbers(text):
            self.add_value(f.value)


def collect(obj: Any, allowed: AllowedNumbers | None = None) -> AllowedNumbers:
    """Every number in a JSON-like object, including numbers written inside strings."""
    a = allowed or AllowedNumbers()
    if isinstance(obj, bool) or obj is None:
        return a
    if isinstance(obj, (int, float)):
        a.add_value(obj)
    elif isinstance(obj, str):
        a.add_text(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            collect(k, a)
            collect(v, a)
    elif isinstance(obj, Iterable):
        for v in obj:
            collect(v, a)
    return a


def check(texts: Iterable[str], allowed: AllowedNumbers, small_counts: int = 12) -> tuple[int, list[str]]:
    """Returns (numbers checked, violations). Small plain counts (1..small_counts) are allowed
    as structure ("3 plans", "two scenarios"); money and percentages must match exactly."""
    n, bad = 0, []
    for text in texts:
        for f in extract_numbers(text):
            n += 1
            if f.kind == "money":
                ok = any(abs(f.value - m) <= 0.5 for m in allowed.money)
            elif f.kind == "pct":
                ok = f.value in allowed.pct
            else:
                ok = f.value in allowed.nums or f.value <= small_counts or 2000 <= f.value <= 2100
            if not ok:
                bad.append(f.text.strip())
    return n, bad
