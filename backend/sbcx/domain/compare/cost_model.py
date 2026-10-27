"""Annual cost simulation (docs/design/v2/06-cost-model.md). Pure functions; every number the UI and
the explanation show about money comes from here.

Unknown inputs become ranges: each plan is simulated at a low and a high bound, e.g. a cell with
`deductible_applies = null` is priced without the deductible (low) and with it (high)."""

from __future__ import annotations

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


def member_pays(cs: CostShare | None, allowed: float, ded_remaining: float, bound: Bound) -> Pay:
    """What the member pays for one claim (06-cost-model §3)."""
    if cs is None or not cs.covered:
        return Pay(allowed, False, 0.0, gap=True)
    applies = cs.deductible_applies
    if applies is None:
        # "No charge" states the member pays nothing, so an unstated deductible doesn't apply to it
        applies = bound == "high" and not (cs.copay == 0 and cs.coinsurance_pct == 0)
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
    for c in claims:
        cs, _ = cell(plan, c.service_key, network)
        p = member_pays(cs, c.allowed, acc.ded_remaining(c.member), bound)
        amt = p.amount
        if p.counts_toward_oop:
            amt = min(amt, acc.oop_remaining(c.member))
            acc.add(c.member, p.to_deductible, amt)
        pays.append(round(amt, 2))
    ded_met = acc.ded_remaining(0) <= 0.005 and bool(d and (d.individual or 0) > 0)
    oop_met = acc.oop_remaining(0) <= 0.005
    return pays, sum(pays), ded_met, oop_met


def simulate(
    doc: BenefitsDocument,
    inputs: PlanInputs,
    scenario: Scenario,
    cfg: ScenarioConfig,
    prices: ReferencePrices,
    tier: CoverageTier = CoverageTier.individual,
    network: Network = Network.in_network,
) -> ScenarioPlanResult:
    plan = doc.benefits
    claims = expand(scenario, cfg, prices)
    if tier == CoverageTier.family and doc.extras.deductible_type == DeductibleType.unknown:
        modes = [True, False]
    else:
        modes = [doc.extras.deductible_type != DeductibleType.aggregate]
    runs = {(b, m): _run(plan, claims, tier, network, b, m) for b in ("low", "high") for m in modes}
    low_key = min((k for k in runs if k[0] == "low"), key=lambda k: runs[k][1])
    high_key = max((k for k in runs if k[0] == "high"), key=lambda k: runs[k][1])
    lo, hi = runs[low_key], runs[high_key]

    assumptions: list[str] = []
    trace = []
    seen_notes = set()
    for i, c in enumerate(claims):
        cs, note = cell(plan, c.service_key, network)
        if note and note not in seen_notes:
            seen_notes.add(note)
            assumptions.append(note.capitalize() + ".")
        flag = ""
        if cs is None or not cs.covered:
            flag = "not covered: full cost, doesn't count toward the out-of-pocket limit"
        elif (
            cs.deductible_applies is None
            and not (cs.copay == 0 and cs.coinsurance_pct == 0)
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
