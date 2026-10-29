"""Deductible and coverage claims in an explanation must agree with the computed comparison
(docs/design/v2.1/02-solution-design.md §2.4). Numbers and superlatives are checked elsewhere; this
catches correct numbers wrapped in a false statement, e.g. "you pay full cost until the deductible is
met" for a plan whose visits have copays before the deductible (2026-10-29 review, F2).

Rules, each on one sentence (C2-C5 on one clause of it):
  C1  "pay full cost until the deductible" about a plan that covers non-preventive care before it
  C2  "<service> ... deductible doesn't apply / before the deductible" when the cell says otherwise
  C3  "<service> ... after the deductible" when the cell says the deductible doesn't apply, or the SBC
      doesn't say
  C4  "doesn't cover <service>" when the plan covers it
  C5  "covers <service>" when the plan doesn't
A service the alias table can't name unambiguously is skipped, never guessed."""

from __future__ import annotations

import re

from sbcx.domain.comparison import CellView, ComparisonResult
from sbcx.domain.explanation import Explanation

# deductible statuses (cost_model.DeductibleStatus) meaning "covered before the deductible"
EXEMPT = {"does_not_apply", "before_per_sbc", "first_visits_before"}
NO_DEDUCTIBLE = {"none"}

# alias -> diff id; checked longest first so "non-preferred brand" wins over "preferred brand"
_ALIASES: list[tuple[str, str]] = [
    (r"primary care( visits?| doctors?)?|\bPCP\b|doctor'?s? visits?", "svc.primary_care_visit"),
    (r"specialists?( visits?| care)?", "svc.specialist_visit"),
    (r"preventive( care| visits?| services)?|screenings?", "svc.preventive_care"),
    (r"diagnostic tests?|lab (work|tests?)|blood work|x-rays?", "svc.diagnostic_test"),
    (r"imaging|\bMRIs?\b|\bCT scans?", "svc.imaging"),
    (r"emergency room( care| visits?)?|\bER\b( visits?| care)?", "svc.emergency_room"),
    (r"ambulance( rides?| services)?|emergency (medical )?transportation", "svc.emergency_transportation"),
    (r"urgent care( visits?)?", "svc.urgent_care"),
    (
        r"mental (or behavioral )?health (therapy|visits?|outpatient( care)?)|outpatient mental health|therapy visits?",
        "svc.mental_health_outpatient",
    ),
    (r"physical therapy|\brehab(ilitation)?( services)?", "svc.rehabilitation"),
    (r"\bhabilitation( services)?", "svc.habilitation"),
    (r"home health( care)?", "svc.home_health_care"),
    (r"skilled nursing( care)?", "svc.skilled_nursing"),
    (r"durable medical equipment|\bDME\b", "svc.durable_medical_equipment"),
    (r"hospice( services| care)?", "svc.hospice"),
    (r"prenatal (care|visits?)|pregnancy (office )?visits?", "svc.pregnancy_office_visits"),
    (r"children'?s eye exams?|pediatric eye exams?", "svc.child_eye_exam"),
    (r"children'?s glasses|pediatric glasses", "svc.child_glasses"),
    (r"children'?s dental( check-?ups?| care)?|pediatric dental", "svc.child_dental_checkup"),
    (r"non-?preferred brand( drugs| medications| prescriptions)?", "drug.non_preferred_brand"),
    (
        r"(?<!non-)(?<!non)preferred brand( drugs| medications| prescriptions)?|brand-name drugs",
        "drug.preferred_brand",
    ),
    (r"generics?( drugs| medications| prescriptions)?", "drug.generic"),
    (r"specialty (drugs|medications|prescriptions)", "drug.specialty"),
]
ALIASES = [(re.compile(rf"(?i)\b(?:{rx})"), key) for rx, key in _ALIASES]

_HEDGE = re.compile(
    r"(?i)\b(depends?|depending|overlap\w*|may|might|could|unclear|uncertain|not stated|whether|"
    r"(do|does|did)\s+not\s+(state|say)|(don|doesn)'?t\s+(state|say))\b"
)
_EXCEPTION = re.compile(r"(?i)\b(except|other than|apart from|besides|aside from|excluding)\b")
_FULL_COST = re.compile(
    r"(?i)(\bpays?|\bpaying)\s+(the\s+)?full\s+(cost|price)[^.;]{0,60}?deductible|nothing is covered[^.;]{0,60}?deductible"
)
_EXEMPT_CLAIM = re.compile(
    r"(?i)deductible\s+(doesn'?t|does not|don'?t|do not)\s+apply|before\s+(the|its|you meet the|meeting the)\s+deductible"
    r"|without\s+(meeting|paying)\s+(the|its)\s+deductible|skips?\s+the\s+deductible|not subject to the deductible"
)
_FULL_PRICE_CONTEXT = re.compile(r"(?i)full (cost|price)|\buntil\b|\bpay (the )?(whole|entire)")
_REQUIRED_CLAIM = re.compile(
    r"(?i)\bafter\s+(the\s+|its\s+|you meet the\s+|meeting the\s+)?deductible|deductible\s+applies|subject to the deductible"
)
_NOT_COVER = re.compile(
    r"(?i)\b(does not|doesn'?t|won'?t|will not|do not|don'?t)\s+cover|\bnot covered\b|\bno coverage for\b|\bexcludes?\b"
)
_COVERS = re.compile(r"(?i)\bcover(s|ed|age)?\b")
_BEFORE_AND = re.compile(r"(?i)\bbefore\s+(and|or)\s+$")
_CLAUSE = re.compile(r"(?i);|\s+(?:while|whereas|but)\s+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _cells(result: ComparisonResult) -> dict[str, dict[str, CellView | None]]:
    out: dict[str, dict[str, CellView | None]] = {d.id: dict(d.cells) for d in result.services}
    out |= {d.id: dict(d.cells) for d in result.drug_tiers}
    return out


def covers_before_deductible(result: ComparisonResult, plan: str) -> list[str]:
    """Diff ids of the non-preventive services and drug tiers this plan covers before the deductible (excluding
    catastrophic first visits, which are a narrow federal exception)."""
    out = []
    for did, cells in _cells(result).items():
        c = cells.get(plan)
        if (
            did != "svc.preventive_care"
            and c
            and c.covered
            and c.deductible_status in {"does_not_apply", "before_per_sbc"}
        ):
            out.append(did)
    return out


def _aliases(text: str) -> list[tuple[int, int, str]]:
    """(start, end, diff id) for service names in text, without overlapping matches."""
    found: list[tuple[int, int, str]] = []
    for rx, key in ALIASES:
        for m in rx.finditer(text):
            found.append((m.start(), m.end(), key))
    found.sort(key=lambda f: (f[0], -(f[1] - f[0])))
    out: list[tuple[int, int, str]] = []
    end = -1
    for s, e, key in found:
        if s >= end:
            out.append((s, e, key))
            end = e
    return out


_LIST_GAP = re.compile(r"(?i)^[\s,]*(?:(?:and|or)\b)?[\s,]*$")


def _groups(aliases: list[tuple[int, int, str]], text: str) -> list[list[tuple[int, int, str]]]:
    """Aliases joined only by list separators ("specialist visits, primary care, or lab work") form one group,
    so a claim about the list applies to each of them."""
    groups: list[list[tuple[int, int, str]]] = []
    for a in aliases:
        if groups and _LIST_GAP.match(text[groups[-1][-1][1] : a[0]]):
            groups[-1].append(a)
        else:
            groups.append([a])
    return groups


def _target(groups: list[list[tuple[int, int, str]]], start: int, end: int, prefer_after: bool = False):
    """The services a claim phrase is about: the group right before it, or right after it when there is none
    (or when prefer_after, for "doesn't cover <service>")."""
    before = [g for g in groups if g[-1][1] <= start]
    after = [g for g in groups if g[0][0] >= end]
    first, second = (after[:1], before[-1:]) if prefer_after else (before[-1:], after[:1])
    return (first or second or [[]])[0]


def _mask(text: str, names: list[str]) -> str:
    """Blank out plan names (same length) so "Moda Bronze ($0 Virtual Urgent Care)" isn't read as urgent care."""
    for n in sorted(names, key=len, reverse=True):
        text = re.sub(re.escape(n), lambda m: " " * len(m.group(0)), text, flags=re.I)
    return text


def _plan_for(pos: int, mentions: list[tuple[int, str]]) -> str | None:
    """The plan named nearest before a position, or the only plan named in the clause."""
    before = [k for p, k in mentions if p < pos]
    if before:
        return before[-1]
    keys = {k for _, k in mentions}
    return next(iter(keys)) if len(keys) == 1 else None


def _cell(
    a: tuple[int, int, str],
    mentions: list[tuple[int, str]],
    only: str | None,
    cells: dict[str, dict[str, CellView | None]],
    labels: dict[str, str],
) -> tuple[CellView | None, str]:
    """The cell a service mention is about, and a description of it for the violation message."""
    who = _plan_for(a[0], mentions) if mentions else only
    c = cells.get(a[2], {}).get(who) if who else None
    return c, f"{labels[a[2]]} on Plan {who}: {c.display if c else ''}"


def deductible_claims(e: Explanation, result: ComparisonResult, facts: dict) -> list[str]:
    from sbcx.domain.explain.generate import _mentions  # plan-name matching shared with claim_check

    cells = _cells(result)
    labels = {d.id: d.label for d in result.services} | {d.id: d.label for d in result.drug_tiers}
    plan_names = [p["name"] for p in facts["plans"]]
    bad: list[str] = []
    texts = [e.headline, *e.key_points, *(s.text for s in e.scenarios), *e.watch_out]
    for text in texts:
        for sent in _SENTENCE.split(text):
            ments = _mentions(sent, facts)
            plans = {k for _, k in ments}
            # C1: one plan, "full cost until the deductible", no stated exception
            if len(plans) == 1 and _FULL_COST.search(sent) and not _EXCEPTION.search(sent):
                plan = next(iter(plans))
                before = covers_before_deductible(result, plan)
                if before:
                    names = ", ".join(labels[d] for d in before[:3])
                    bad.append(f'[C1] "{sent.strip()}" — Plan {plan} covers {names} before the deductible')
            if _HEDGE.search(sent):
                continue
            only = next(iter(plans)) if len(plans) == 1 else None
            for clause in _CLAUSE.split(sent):
                if not clause:
                    continue
                cm = _mentions(clause, facts)
                exc = _EXCEPTION.search(clause)
                # "applies to everything except preventive care": services after the marker are the exception
                aliases = [a for a in _aliases(_mask(clause, plan_names)) if not (exc and a[0] > exc.start())]
                groups = _groups(aliases, clause)

                # C2 / C3: a deductible phrase, about the services listed next to it
                timing = False
                for m in [*_EXEMPT_CLAIM.finditer(clause), *_REQUIRED_CLAIM.finditer(clause)]:
                    timing = True
                    exempt = bool(_EXEMPT_CLAIM.fullmatch(m.group(0)))
                    lead = clause[: m.start()]
                    if _BEFORE_AND.search(lead):
                        continue  # "$120 before and after the deductible": true either way
                    if exempt and m.group(0).lower().startswith("before") and not _COVERS.search(lead):
                        continue  # "charges $250 before the deductible" is about timing, not an exemption
                    if exempt and (_NOT_COVER.search(lead) or _FULL_PRICE_CONTEXT.search(clause)):
                        exempt = False  # "doesn't cover X before the deductible" says the deductible applies
                    for a in _target(groups, m.start(), m.end()):
                        c, where = _cell(a, cm, only, cells, labels)
                        if c is None or not c.covered:
                            continue
                        if exempt and c.deductible_status not in EXEMPT | NO_DEDUCTIBLE:
                            bad.append(f'[C2] "{sent.strip()}" — {where}')
                        elif not exempt and c.deductible_status in {
                            "does_not_apply",
                            "before_per_sbc",
                            "not_stated",
                        }:
                            bad.append(f'[C3] "{sent.strip()}" — {where}')
                if timing or _FULL_PRICE_CONTEXT.search(clause):
                    continue  # coverage words here are about timing, not about whether the plan covers it
                # C4 / C5: coverage claims
                neg = _NOT_COVER.search(clause)
                pos = None if neg else _COVERS.search(clause)
                m2 = neg or pos
                if m2 is None:
                    continue
                for a in _target(groups, m2.start(), m2.end(), prefer_after=True):
                    c, where = _cell(a, cm, only, cells, labels)
                    if c is None:
                        continue
                    if neg and c.covered:
                        bad.append(f'[C4] "{sent.strip()}" — {where}')
                    elif pos and c.covered is False:
                        bad.append(f'[C5] "{sent.strip()}" — {where}')
    return list(dict.fromkeys(bad))
