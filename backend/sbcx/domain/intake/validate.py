"""Keep only events grounded in the user's description (validator rules 1-4)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sbcx.domain.intake.rules import TIER_WORDS, allowed_counts
from sbcx.domain.intake.schema import DraftEvent, Unmodeled, UsageDraft


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


@dataclass
class Checked:
    events: list[DraftEvent] = field(default_factory=list)
    unmodeled: list[Unmodeled] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)


def validate(draft: UsageDraft, text: str, event_types: dict[str, Any], members: int) -> Checked:
    """members: household size (1 for individual coverage)."""
    out = Checked()
    src = _norm(text)
    merged: dict[tuple[str, int], DraftEvent] = {}
    for e in draft.events:
        quote = _norm(e.quote)
        if e.event not in event_types:
            out.violations.append(f"unknown event {e.event!r}")
        elif not 0 <= e.member < members:
            out.violations.append(f"{e.event}: member {e.member} doesn't exist (household of {members})")
        elif not quote or quote not in src:
            out.violations.append(f"{e.event}: quote {e.quote!r} is not in the description")
        elif not 1 <= e.count <= 365 or e.count not in allowed_counts(quote):
            out.violations.append(f"{e.event}: count {e.count} isn't supported by {e.quote!r}")
        elif e.event in TIER_WORDS and not TIER_WORDS[e.event].search(quote):
            out.violations.append(
                f"{e.event}: {e.quote!r} doesn't say which kind of drug it is; move it to unmodeled"
            )
        else:
            key = (e.event, e.member)
            if key in merged:
                prev = merged[key]
                merged[key] = prev.model_copy(
                    update={"count": min(365, prev.count + e.count), "quote": f"{prev.quote}; {e.quote}"}
                )
            else:
                merged[key] = e
    out.events = list(merged.values())
    for u in draft.unmodeled:
        if _norm(u.quote) and _norm(u.quote) in src:
            out.unmodeled.append(u)
        else:
            out.violations.append(f"unmodeled quote {u.quote!r} is not in the description")
    return out
