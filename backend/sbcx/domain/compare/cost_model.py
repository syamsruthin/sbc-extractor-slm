"""Annual cost simulation (docs/design/v2/06-cost-model.md). Pure functions; every number the UI and
the explanation show about money comes from here.

Unknown inputs become ranges: each plan is simulated at a low and a high bound, e.g. a cell with
`deductible_applies = null` is priced without the deductible (low) and with it (high)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from sbcx.domain.benefits import BenefitsDocument, DeductibleType
from sbcx.domain.compare.config import ReferencePrices, ScenarioConfig
from sbcx.domain.comparison import (
    CoverageTier,
    LineItem,
    Money,
    Network,
    PlanInputs,
    Scenario,
    ScenarioPlanResult,
)
from sbcx.domain.sbc import CostShare, DrugTier, SBCExtraction

Bound = Literal["low", "high"]
DRUG_ORDER = ["generic", "preferred_brand", "non_preferred_brand", "specialty"]


@dataclass
class Claim:
    event: str
    service_key: str  # service key or "drug:<category>"
    allowed: float
    member: int = 0


@dataclass
class Pay:
    amount: float
    counts_toward_oop: bool
    to_deductible: float
    gap: bool = False


HintReason = Literal["", "page1", "hsa", "catastrophic"]


@dataclass(frozen=True)
class DeductibleHints:
    """Evidence about cells whose own row doesn't say whether the deductible applies: the SBC's page-1
    answer to "Are there services covered before you meet your deductible?" and plan-type rules."""

    unmarked_apply: bool = False  # unmarked rows apply the deductible
    before: frozenset[str] = frozenset()  # services covered before the deductible
    reason: HintReason = ""  # why unmarked rows apply
    pcp_visits_before: int = 0  # catastrophic plans: this many primary care visits come before the deductible


_BEFORE = {
    "preventive_care": r"preventive",
    "primary_care_visit": r"primary care|\bpcp\b",
    "specialist_visit": r"specialist",
    "urgent_care": r"urgent",
    "mental_health_outpatient": r"mental|behavioral",
    "diagnostic_test": r"diagnostic|\blab",
    "imaging": r"imaging",
    "drug:generic": r"generic|prescription|\bdrugs?\b",
    "drug:preferred_brand": r"preferred brand|prescription|\bdrugs?\b",
    "drug:non_preferred_brand": r"prescription",
    "drug:specialty": r"prescription",
}


# Plan types whose deductible applies to everything except preventive care by federal rule: HSA-eligible
# high-deductible plans (IRS), and catastrophic plans, which must also cover 3 primary care visits first.
_HSA = re.compile(r"(?i)\bH\.?\s?S\.?\s?A\b|\bHDHP\b|high[- ]deductible")
_CATASTROPHIC = re.compile(r"(?i)catastrophic")


def deductible_hints(
    plan: SBCExtraction, metal: str | None = None, hsa_eligible: bool | None = None
) -> DeductibleHints:
    """`metal` and `hsa_eligible` come from the CMS Plan Attributes PUF for catalog plans; uploads have
    neither, so the plan name is used to recognise catastrophic and HSA plans."""
    items = " | ".join(plan.services_before_deductible).lower()
    unmarked = bool(
        re.search(r"deductible\W{0,3}(does not|doesn.t) apply|listed (below|in the chart)", items)
    )
    named = frozenset(k for k, rx in _BEFORE.items() if re.search(rx, items))
    label = f"{plan.plan_name or ''} {plan.plan_type or ''}"
    if (metal or "").lower() == "catastrophic" or (metal is None and _CATASTROPHIC.search(label)):
        return DeductibleHints(True, named, "catastrophic", pcp_visits_before=3)
    if hsa_eligible or (hsa_eligible is None and _HSA.search(label)):
        return DeductibleHints(True, named, "hsa")
    return DeductibleHints(unmarked, named, "page1" if unmarked else "")


def _first_visits_rule(cs: CostShare, service_key: str, h: DeductibleHints) -> bool:
    """Catastrophic plans cover only the first visits to primary care before the deductible (federal rule). A row
    saying "deductible does not apply" (or nothing) describes those visits; one saying it applies is kept as is."""
    return (
        service_key == "primary_care_visit" and h.pcp_visits_before > 0 and cs.deductible_applies is not True
    )


def resolve_applies(
    cs: CostShare,
    service_key: str,
    bound: Bound,
    hints: DeductibleHints | None = None,
    visit: int | None = None,
) -> bool:
    """Whether the deductible applies to a claim. The row's own statement wins; otherwise in-network
    preventive care is free (required by federal law), page-1 evidence decides, and only then is it
    a range (low bound: doesn't apply, high bound: applies). "No charge" alone is not evidence: SBC
    charts show costs after the deductible is met."""
    h = hints or DeductibleHints()
    if _first_visits_rule(cs, service_key, h):
        return visit is not None and visit > h.pcp_visits_before  # visit is 1-based
    if cs.deductible_applies is not None:
        return cs.deductible_applies
    if service_key == "preventive_care" or service_key in h.before:
        return False
    if h.unmarked_apply:
        return True
    return bound == "high"


DeductibleStatus = Literal[
    "applies",
    "does_not_apply",
    "applies_per_sbc",
    "applies_hsa_rules",
    "applies_catastrophic_rules",
    "first_visits_before",
    "before_per_sbc",
    "not_stated",
    "none",
]


def deductible_status(
    cs: CostShare | None, service_key: str, hints: DeductibleHints | None, has_deductible: bool
) -> DeductibleStatus:
    """What we know about the deductible for one cell, so text shown to users and to the LLM never turns
    "the SBC doesn't say" into "no deductible" (2026-10-28 quality review)."""
    if cs is None or not cs.covered or not has_deductible:
        return "none"
    h = hints or DeductibleHints()
    if _first_visits_rule(cs, service_key, h):
        return "first_visits_before"
    if cs.deductible_applies is True:
        return "applies"
    if cs.deductible_applies is False:
        return "does_not_apply"
    if service_key == "preventive_care" or service_key in h.before:
        return "before_per_sbc"
    if h.unmarked_apply:
        if h.reason == "hsa":
            return "applies_hsa_rules"
        if h.reason == "catastrophic":
            return "applies_catastrophic_rules"
        return "applies_per_sbc"
    return "not_stated"


def has_deductible(plan: SBCExtraction, network: Network = Network.in_network) -> bool:
    d = getattr(plan.deductible, network.value)
    return bool(d and ((d.individual or 0) > 0 or (d.family or 0) > 0))


def member_pays(
    cs: CostShare | None, allowed: float, ded_remaining: float, bound: Bound, applies: bool | None = None
) -> Pay:
    """What the member pays for one claim (06-cost-model §3)."""
    if cs is None or not cs.covered:
        return Pay(allowed, False, 0.0, gap=True)
    if applies is None:
        applies = cs.deductible_applies if cs.deductible_applies is not None else bound == "high"
    to_ded = min(allowed, max(0.0, ded_remaining)) if applies else 0.0
    rest = allowed - to_ded
    share = 0.0
    if rest > 0:
        copay, pct = cs.copay, (cs.coinsurance_pct / 100 if cs.coinsurance_pct is not None else None)
        if copay is not None and pct is not None:
            share = min(rest, copay + max(0.0, rest - copay) * pct)
        elif copay is not None:
            share = min(copay, rest)
        elif pct is not None:
            share = rest * pct
        else:
            share = 0.0 if bound == "low" else rest
    return Pay(to_ded + share, True, to_ded)


def drug_tier(tiers: list[DrugTier], category: str) -> tuple[DrugTier | None, str | None]:
    """Lowest-cost tier of a category; plans that label tiers only by number fall back to position."""
    for t in tiers:
        if t.category.value == category:
            return t, None
    if not tiers:
        return None, "no drug tiers in the SBC"
    i = min(DRUG_ORDER.index(category), len(tiers) - 1)
    return tiers[i], f"{category.replace('_', ' ')} priced at tier {i + 1} ({tiers[i].name}) by position"


def cell(plan: SBCExtraction, service_key: str, network: Network) -> tuple[CostShare | None, str | None]:
    if service_key.startswith("drug:"):
        t, note = drug_tier(plan.drug_tiers, service_key.removeprefix("drug:"))
        return (getattr(t.retail, network.value) if t else None), note
    return getattr(getattr(plan.services, service_key), network.value), None


def expand(scenario: Scenario, cfg: ScenarioConfig, prices: ReferencePrices) -> list[Claim]:
    claims = []
    for ev in scenario.events:
        et = cfg.event_types.get(ev.event)
        if et is None:
            continue
        for _ in range(ev.count):
            if "drug" in et:
                claims.append(Claim(ev.event, f"drug:{et['drug']}", prices.drugs[et["drug"]], ev.member))
            for s in et.get("services", []):
                claims.append(Claim(ev.event, s, prices.services[s], ev.member))
    return claims


@dataclass
class Accumulators:
    """Deductible and OOP remaining, per member and for the family."""

    ind_ded: float | None
    fam_ded: float | None
    ind_oop: float | None
    fam_oop: float | None
    family: bool
    embedded: bool
    spent_ded: dict[int, float] = field(default_factory=dict)
    spent_oop: dict[int, float] = field(default_factory=dict)

    def ded_remaining(self, m: int) -> float:
        fam_spent = sum(self.spent_ded.values())
        if not self.family:
            return max(0.0, (self.ind_ded or 0.0) - self.spent_ded.get(m, 0.0))
        fam_left = max(
            0.0, (self.fam_ded if self.fam_ded is not None else 2 * (self.ind_ded or 0.0)) - fam_spent
        )
        if self.embedded and self.ind_ded is not None:
            return min(fam_left, max(0.0, self.ind_ded - self.spent_ded.get(m, 0.0)))
        return fam_left

    def oop_remaining(self, m: int) -> float:
        inf = float("inf")
        ind = inf if self.ind_oop is None else max(0.0, self.ind_oop - self.spent_oop.get(m, 0.0))
        if not self.family:
            return ind
        fam_cap = (
            self.fam_oop
            if self.fam_oop is not None
            else (2 * self.ind_oop if self.ind_oop is not None else None)
        )
        fam = inf if fam_cap is None else max(0.0, fam_cap - sum(self.spent_oop.values()))
        return min(ind, fam)  # ACA: individual OOP limit is embedded in family coverage

    def add(self, m: int, ded: float, oop: float) -> None:
        self.spent_ded[m] = self.spent_ded.get(m, 0.0) + ded
        self.spent_oop[m] = self.spent_oop.get(m, 0.0) + oop


def _amounts(plan: SBCExtraction, network: Network):
    return getattr(plan.deductible, network.value), getattr(plan.out_of_pocket_limit, network.value)


def oop_limit(plan: SBCExtraction, tier: CoverageTier, network: Network = Network.in_network) -> float | None:
    _, o = _amounts(plan, network)
    if o is None:
        return None
    if tier == CoverageTier.family:
        return o.family if o.family is not None else (2 * o.individual if o.individual is not None else None)
    return o.individual


def _run(
    plan: SBCExtraction,
    claims: list[Claim],
    tier: CoverageTier,
    network: Network,
    bound: Bound,
    embedded: bool,
    hints: DeductibleHints,
) -> tuple[list[float], float, bool, bool]:
    d, o = _amounts(plan, network)
    acc = Accumulators(
        ind_ded=d.individual if d else 0.0,
        fam_ded=d.family if d else None,
        ind_oop=o.individual if o else None,
        fam_oop=o.family if o else None,
        family=tier == CoverageTier.family,
        embedded=embedded,
    )
    pays: list[float] = []
    for c, visit in zip(claims, _visit_numbers(claims), strict=True):
        cs, _ = cell(plan, c.service_key, network)
        applies = (
            resolve_applies(cs, c.service_key, bound, hints, visit) if cs is not None and cs.covered else None
        )
        p = member_pays(cs, c.allowed, acc.ded_remaining(c.member), bound, applies)
        amt = p.amount
        if p.counts_toward_oop:
            amt = min(amt, acc.oop_remaining(c.member))
            acc.add(c.member, p.to_deductible, amt)
        pays.append(round(amt, 2))
    ded_met = acc.ded_remaining(0) <= 0.005 and bool(d and (d.individual or 0) > 0)
    oop_met = acc.oop_remaining(0) <= 0.005
    return pays, sum(pays), ded_met, oop_met


def _visit_numbers(claims: list[Claim]) -> list[int]:
    """1-based count of each claim among the same member's claims for the same service."""
    seen: dict[tuple[int, str], int] = {}
    out = []
    for c in claims:
        k = (c.member, c.service_key)
        seen[k] = seen.get(k, 0) + 1
        out.append(seen[k])
    return out


RULE_NOTES = {
    "hsa": "HSA-eligible plan: by federal rule the deductible applies to everything except preventive care, "
    "so it is applied wherever the SBC row doesn't say otherwise.",
    "catastrophic": "Catastrophic plan: by federal rule the deductible applies to everything except preventive "
    "care and the first 3 primary care visits, so it is applied wherever the SBC row doesn't say otherwise.",
    "page1": "The SBC says only services marked 'deductible does not apply' are covered before the deductible, "
    "so the deductible is applied to the other services.",
}


def simulate(
    doc: BenefitsDocument,
    inputs: PlanInputs,
    scenario: Scenario,
    cfg: ScenarioConfig,
    prices: ReferencePrices,
    tier: CoverageTier = CoverageTier.individual,
    network: Network = Network.in_network,
    hints: DeductibleHints | None = None,
) -> ScenarioPlanResult:
    """`hints` defaults to what the document alone shows; pass `deductible_hints(plan, metal, hsa_eligible)`
    when catalog metadata is known. Plan-specific notes come first in `assumptions`."""
    plan = doc.benefits
    hints = hints or deductible_hints(plan)
    claims = expand(scenario, cfg, prices)
    if tier == CoverageTier.family and doc.extras.deductible_type == DeductibleType.unknown:
        modes = [True, False]
    else:
        modes = [doc.extras.deductible_type != DeductibleType.aggregate]
    runs = {(b, m): _run(plan, claims, tier, network, b, m, hints) for b in ("low", "high") for m in modes}
    # The cheaper run is the low bound and the dearer one the high bound, whatever assumptions produced
    # them: applying the deductible earlier can leave less room under the OOP cap for later claims.
    low_key = min(runs, key=lambda k: runs[k][1])
    high_key = max(runs, key=lambda k: runs[k][1])
    lo, hi = runs[low_key], runs[high_key]

    assumptions: list[str] = [RULE_NOTES[hints.reason]] if hints.unmarked_apply and hints.reason else []
    trace = []
    seen_notes = set()
    for i, (c, visit) in enumerate(zip(claims, _visit_numbers(claims), strict=True)):
        cs, note = cell(plan, c.service_key, network)
        if note and note not in seen_notes:
            seen_notes.add(note)
            assumptions.append(note.capitalize() + ".")
        flag = ""
        if cs is None or not cs.covered:
            flag = "not covered: full cost, doesn't count toward the out-of-pocket limit"
        elif (
            cs.deductible_applies is None
            and resolve_applies(cs, c.service_key, "low", hints, visit)
            != resolve_applies(cs, c.service_key, "high", hints, visit)
            and (d := _amounts(plan, network)[0])
            and (d.individual or 0) > 0
        ):
            flag = "SBC doesn't say whether the deductible applies"
        trace.append(
            LineItem(
                event=c.event,
                service_key=c.service_key,
                allowed=c.allowed,
                member_pays=Money(low=lo[0][i], high=hi[0][i]),
                note=flag,
            )
        )
    d, o = _amounts(plan, network)
    if o is None:
        assumptions.append("No out-of-pocket limit was found for this network, so costs aren't capped.")
    if d is None:
        assumptions.append("No deductible was found for this network; treated as $0.")
    if len(modes) == 2:
        assumptions.append(
            "The SBC doesn't say whether the family deductible is embedded or aggregate; both were tried."
        )

    premium = round(inputs.monthly_premium * 12, 2) if inputs.monthly_premium is not None else None
    fixed = (premium or 0.0) - inputs.employer_hsa_hra_annual
    oop = Money(low=round(lo[1], 2), high=round(hi[1], 2))
    return ScenarioPlanResult(
        annual_premium=premium,
        contribution=inputs.employer_hsa_hra_annual,
        out_of_pocket=oop,
        total=Money(low=round(fixed + oop.low, 2), high=round(fixed + oop.high, 2)),
        deductible_met=lo[2] and hi[2],
        oop_limit_met=hi[3],
        trace=trace,
        assumptions=assumptions,
    )
