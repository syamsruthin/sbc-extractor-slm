"""Deterministic comparison of 2-5 plans: per-service differences, drug tiers, coverage gaps, annual
cost per scenario and impact ranking. Same inputs + ENGINE_VERSION -> identical result (hashed)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from string import ascii_uppercase

from sbcx.domain.benefits import BenefitsDocument, Warning
from sbcx.domain.compare.config import ReferencePrices, ScenarioConfig
from sbcx.domain.compare.cost_model import (
    DRUG_ORDER,
    RULE_NOTES,
    DeductibleHints,
    deductible_hints,
    deductible_status,
    drug_tier,
    has_deductible,
    member_pays,
    oop_limit,
    resolve_applies,
    simulate,
)
from sbcx.domain.comparison import (
    AmountsView,
    CellView,
    ComparisonRequest,
    ComparisonResult,
    DrugTierDiff,
    Headline,
    Money,
    OverallVerdict,
    PlanInputs,
    PlanRef,
    RankedDiff,
    Scenario,
    ScenarioResult,
    ServiceDiff,
    Verdict,
)
from sbcx.domain.display import DRUG_LABELS, SERVICE_LABELS, describe_cost
from sbcx.domain.enrich.sections import SERVICE_SECTION
from sbcx.domain.sbc import CostShare, SBCExtraction
from sbcx.versions import ENGINE_VERSION

ASSUMPTIONS = [
    "Estimates use reference prices for each service; real prices vary by provider and region.",
    "Costs are for in-network care unless out-of-network was selected.",
    "Balance billing, separate drug deductibles, visit limits and HSA tax savings aren't included.",
    "Where the SBC doesn't say whether the deductible applies, costs are shown as a range.",
]


@dataclass
class PlanInput:
    document_id: str
    doc: BenefitsDocument
    catalog_plan_id: str | None = None
    metal: str | None = None
    coverage_examples: dict | None = None
    hsa_eligible: bool | None = None  # CMS PUF flag; None for uploads (the plan name is used instead)


def est_per_use(cs: CostShare | None, allowed: float) -> float | None:
    """Expected member cost for one use once the deductible is met."""
    if cs is None:
        return None
    if cs.covered and cs.copay is None and cs.coinsurance_pct is None:
        return None
    return round(member_pays(cs, allowed, 0.0, "low").amount, 2)


def est_before_deductible(
    cs: CostShare | None, key: str, allowed: float, hints: DeductibleHints | None, deductible: float
) -> Money | None:
    """Member cost for one use (the first visit) before the deductible is met: a range when the SBC
    doesn't say whether the deductible applies. A service the plan doesn't cover costs the full price, as in
    est_per_use."""
    if cs is None:
        return None
    if not cs.covered:
        return Money(low=round(allowed, 2), high=round(allowed, 2))
    if cs.copay is None and cs.coinsurance_pct is None:
        return None
    pay = {
        b: member_pays(cs, allowed, deductible, b, resolve_applies(cs, key, b, hints, visit=1)).amount
        for b in ("low", "high")
    }
    lo, hi = sorted((round(pay["low"], 2), round(pay["high"], 2)))
    return Money(low=lo, high=hi)


def view(
    cs: CostShare | None,
    allowed: float | None,
    status: str | None = None,
    before: Money | None = None,
) -> CellView:
    return CellView(
        display=describe_cost(cs, status=status),
        deductible_status=status,
        covered=None if cs is None else cs.covered,
        copay=cs.copay if cs else None,
        coinsurance_pct=cs.coinsurance_pct if cs else None,
        deductible_applies=cs.deductible_applies if cs else None,
        est_cost_per_use=est_per_use(cs, allowed) if allowed is not None else None,
        est_cost_before_deductible=before,
        note=cs.note if cs else None,
    )


def _kind(cs: CostShare | None) -> str | None:
    if cs is None or not cs.covered:
        return "nc"
    if cs.copay == 0 and cs.coinsurance_pct == 0:
        return "free"
    if cs.copay is not None and cs.coinsurance_pct is None:
        return "copay"
    if cs.coinsurance_pct is not None and cs.copay is None:
        return "pct"
    return "mixed" if cs.copay is not None else None


def verdict(base: CellView, other: CellView, allowed: float) -> tuple[Verdict, float | None]:
    b, o = base.est_cost_per_use, other.est_cost_per_use
    if b is None or o is None:
        return Verdict.not_comparable, None
    delta = round(o - b, 2)
    if abs(delta) < max(1.0, 0.02 * allowed):
        return Verdict.same, delta
    return (Verdict.better if delta < 0 else Verdict.worse), delta


def _individual_deductible(plan: SBCExtraction, network: str) -> float:
    """One use before the deductible is one member's claim, so the individual deductible applies."""
    d = getattr(plan.deductible, network)
    return float(d.individual or 0.0) if d else 0.0


def range_verdict(base: Money | None, other: Money | None, allowed: float) -> Verdict:
    """Verdict for two cost ranges: better/worse only when the ranges don't overlap (beyond the tolerance)."""
    if base is None or other is None:
        return Verdict.not_comparable
    tol = max(1.0, 0.02 * allowed)
    if other.high + tol < base.low:
        return Verdict.better
    if other.low > base.high + tol:
        return Verdict.worse
    if abs(other.low - base.low) <= tol and abs(other.high - base.high) <= tol:
        return Verdict.same
    return Verdict.not_comparable


def overall_verdict(after: Verdict, before: Verdict) -> OverallVerdict:
    """Combine the after- and before-deductible verdicts (docs/design/v2.1/02-solution-design.md §2.2)."""
    if after == before:
        return OverallVerdict(after.value)
    if {after, before} <= {Verdict.better, Verdict.same}:
        return OverallVerdict.better
    if {after, before} <= {Verdict.worse, Verdict.same}:
        return OverallVerdict.worse
    return OverallVerdict.depends_on_deductible


def _diff(
    id_: str,
    cells: dict[str, CostShare | None],
    base: str,
    allowed: float,
    statuses: Mapping[str, str] | None = None,
    befores: Mapping[str, Money | None] | None = None,
) -> tuple[dict, dict, dict, str, list[str], dict, dict]:
    views = {k: view(c, allowed, (statuses or {}).get(k), (befores or {}).get(k)) for k, c in cells.items()}
    verdicts, deltas, before_v, overall = {}, {}, {}, {}
    for k in views:
        if k == base:
            continue
        verdicts[k], deltas[k] = verdict(views[base], views[k], allowed)
        b, o = views[base].est_cost_before_deductible, views[k].est_cost_before_deductible
        before_v[k] = range_verdict(b, o, allowed)
        overall[k] = (
            OverallVerdict.not_comparable
            if b is None
            or o is None
            or views[base].est_cost_per_use is None
            or views[k].est_cost_per_use is None
            else overall_verdict(verdicts[k], before_v[k])
        )
    kinds = {_kind(c) for c in cells.values()}
    kind = "none" if None in kinds else ("exact" if len(kinds - {"free", "nc"}) <= 1 else "estimated")
    flags = []
    if len({v.covered for v in views.values() if v.covered is not None}) > 1:
        flags.append("coverage_gap")
    if {True, False} <= {v.deductible_applies for v in views.values()}:
        flags.append("deductible_difference")
    return views, verdicts, deltas, kind, flags, before_v, overall


def _service_impacts(results: dict[str, ScenarioResult], base: str) -> dict[str, float]:
    """Per service key: weighted |cost difference vs base| across scenarios (selected scenario weight 1)."""
    out: dict[str, float] = {}
    for sid, sr in results.items():
        w = 1.0 if sid in ("custom", "moderate") else 0.25
        per_plan: dict[str, dict[str, float]] = {}
        for pk, r in sr.per_plan.items():
            acc: dict[str, float] = {}
            for li in r.trace:
                acc[li.service_key] = (
                    acc.get(li.service_key, 0.0) + (li.member_pays.low + li.member_pays.high) / 2
                )
            per_plan[pk] = acc
        keys = {k for acc in per_plan.values() for k in acc}
        for k in keys:
            diff = max(abs(per_plan[pk].get(k, 0.0) - per_plan[base].get(k, 0.0)) for pk in per_plan)
            out[k] = out.get(k, 0.0) + w * diff
    return out


def _plan_note(note: str, keys: list[str], by_key: Mapping[str, PlanInput]) -> str:
    who = [
        f"{k} ({by_key[k].doc.benefits.plan_name})" if by_key[k].doc.benefits.plan_name else k
        for k in sorted(keys)
    ]
    label = f"Plan {who[0]}" if len(who) == 1 else f"Plans {', '.join(who[:-1])} and {who[-1]}"
    return f"{label}: {note}"


def compare(
    plans: list[PlanInput], req: ComparisonRequest, cfg: ScenarioConfig, base_prices: ReferencePrices
) -> ComparisonResult:
    prices = base_prices.with_overrides(req.reference_price_overrides)
    keys = list(ascii_uppercase[: len(plans)])
    base_id = req.base_document_id or plans[0].document_id
    by_key = dict(zip(keys, plans, strict=True))
    base = next(k for k, p in by_key.items() if p.document_id == base_id)
    net = req.network.value

    refs = [
        PlanRef(
            plan_key=k,
            document_id=p.document_id,
            catalog_plan_id=p.catalog_plan_id,
            plan_name=p.doc.benefits.plan_name,
            issuer=p.doc.benefits.issuer,
            plan_type=p.doc.benefits.plan_type,
            metal=p.metal,
            is_base=k == base,
        )
        for k, p in by_key.items()
    ]
    inputs: dict[str, PlanInputs] = {
        k: req.inputs.get(p.document_id)
        or req.inputs.get(p.catalog_plan_id or "")
        or PlanInputs.model_validate({})
        for k, p in by_key.items()
    }

    # headline
    def amounts(a) -> AmountsView | None:
        return AmountsView(individual=a.individual, family=a.family) if a else None

    prem: dict[str, float | None] = {
        k: (round(i.monthly_premium * 12, 2) if i.monthly_premium is not None else None)
        for k, i in inputs.items()
    }
    contrib = {k: i.employer_hsa_hra_annual for k, i in inputs.items()}
    best: dict[str, float | None] = {}
    worst: dict[str, float | None] = {}
    for k, p in by_key.items():
        pk = prem[k]
        best[k] = None if pk is None else round(pk - contrib[k], 2)
        lim = oop_limit(p.doc.benefits, req.coverage_tier, req.network)
        bk = best[k]
        worst[k] = None if bk is None or lim is None else round(bk + lim, 2)

    def delta(d: dict[str, float | None]) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        b = d[base]
        for k in keys:
            if k != base:
                v = d[k]
                out[k] = None if v is None or b is None else round(v - b, 2)
        return out

    headline = Headline(
        annual_premium=prem,
        employer_contribution=contrib,
        deductible={k: amounts(getattr(p.doc.benefits.deductible, net)) for k, p in by_key.items()},
        oop_limit={k: amounts(getattr(p.doc.benefits.out_of_pocket_limit, net)) for k, p in by_key.items()},
        best_case=best,
        worst_case=worst,
        best_case_delta=delta(best),
        worst_case_delta=delta(worst),
    )

    hints = {k: deductible_hints(p.doc.benefits, p.metal, p.hsa_eligible) for k, p in by_key.items()}
    has_ded = {k: has_deductible(p.doc.benefits, req.network) for k, p in by_key.items()}
    ded_amt = {
        k: _individual_deductible(p.doc.benefits, net) if has_ded[k] else 0.0 for k, p in by_key.items()
    }

    # services
    services = []
    for skey, label in SERVICE_LABELS.items():
        allowed = prices.services[skey]
        cells = {k: getattr(getattr(p.doc.benefits.services, skey), net) for k, p in by_key.items()}
        st = {k: deductible_status(cells[k], skey, hints[k], has_ded[k]) for k in cells}
        bd = {k: est_before_deductible(cells[k], skey, allowed, hints[k], ded_amt[k]) for k in cells}
        views, verdicts, deltas, kind, flags, before_v, overall = _diff(
            f"svc.{skey}", cells, base, allowed, st, bd
        )
        services.append(
            ServiceDiff(
                id=f"svc.{skey}",
                service_key=skey,
                label=label,
                section=SERVICE_SECTION[skey],
                cells=views,
                verdicts=verdicts,
                delta_per_use=deltas,
                comparison_kind=kind,  # type: ignore[arg-type]
                reference_price=allowed,
                flags=flags,
                verdicts_before_deductible=before_v,
                overall_verdicts=overall,
            )
        )

    drugs = []
    for cat in DRUG_ORDER:
        allowed = prices.drugs[cat]
        tiers = {k: drug_tier(p.doc.benefits.drug_tiers, cat)[0] for k, p in by_key.items()}
        cells = {k: (getattr(t.retail, net) if t else None) for k, t in tiers.items()}
        st = {k: deductible_status(cells[k], f"drug:{cat}", hints[k], has_ded[k]) for k in cells}
        bd = {k: est_before_deductible(cells[k], f"drug:{cat}", allowed, hints[k], ded_amt[k]) for k in cells}
        views, verdicts, deltas, _, _, before_v, overall = _diff(f"drug.{cat}", cells, base, allowed, st, bd)
        drugs.append(
            DrugTierDiff(
                id=f"drug.{cat}",
                category=cat,
                label=DRUG_LABELS[cat],
                cells=dict(views),
                tier_names={k: (t.name if t else None) for k, t in tiers.items()},
                verdicts=verdicts,
                delta_per_use=deltas,
                reference_price=allowed,
                verdicts_before_deductible=before_v,
                overall_verdicts=overall,
            )
        )

    gaps = [s.id for s in services if "coverage_gap" in s.flags]

    # scenarios
    scen: list[Scenario] = [sc for sid in req.scenario_ids if (sc := cfg.preset(sid))]
    if req.custom_scenario and req.custom_scenario.events:
        scen.append(req.custom_scenario.model_copy(update={"id": "custom"}))
    results: dict[str, ScenarioResult] = {}
    plan_notes: dict[str, list[str]] = {}  # note -> plan keys it applies to, in first-seen order
    for sc in scen:
        per = {
            k: simulate(p.doc, inputs[k], sc, cfg, prices, req.coverage_tier, req.network, hints[k])
            for k, p in by_key.items()
        }
        min_high = min(r.total.high for r in per.values())
        cheapest = [k for k, r in per.items() if r.total.low <= min_high + 0.005]
        overlap = len(cheapest) > 1 and any(r.total.low != r.total.high for r in per.values())
        dvb = {
            k: Money(
                low=round(r.total.low - per[base].total.high, 2),
                high=round(r.total.high - per[base].total.low, 2),
            )
            for k, r in per.items()
            if k != base
        }
        results[sc.id] = ScenarioResult(
            scenario=sc, per_plan=per, cheapest=cheapest, delta_vs_base=dvb, ranges_overlap=overlap
        )
        for k, r in per.items():
            for a in r.assumptions:
                keys = plan_notes.setdefault(a, [])
                if k not in keys:
                    keys.append(k)
    # plan-specific notes first, each naming its plans, then the general ones
    # (deductible-rule notes lead: they change the most numbers)
    ordered = sorted(plan_notes.items(), key=lambda kv: kv[0] not in RULE_NOTES.values())
    assumptions = [_plan_note(a, keys, by_key) for a, keys in ordered] + list(ASSUMPTIONS)

    # ranking
    impacts = _service_impacts(results, base)
    ranked = []
    for d in services:
        imp = round(impacts.get(d.service_key, 0.0), 2)
        if "coverage_gap" in d.flags:
            imp = max(imp, d.reference_price or 0.0)
        if imp > 0 or d.flags:
            sev = "high" if ("coverage_gap" in d.flags or imp >= 500) else ("medium" if imp >= 100 else "low")
            ranked.append(RankedDiff(diff_id=d.id, label=d.label, impact_usd=imp, severity=sev))  # type: ignore[arg-type]
    for d2 in drugs:
        imp = round(impacts.get(f"drug:{d2.category}", 0.0), 2)
        if imp > 0:
            ranked.append(
                RankedDiff(
                    diff_id=d2.id,
                    label=d2.label,
                    impact_usd=imp,
                    severity="high" if imp >= 500 else ("medium" if imp >= 100 else "low"),
                )
            )
    ranked.sort(key=lambda r: (-r.impact_usd, r.diff_id))

    warnings: list[Warning] = []
    for k, p in by_key.items():
        if inputs[k].monthly_premium is None:
            warnings.append(
                Warning(
                    code="W_PREMIUM_MISSING",
                    path=k,
                    message=f"Plan {k}: no premium entered, so annual totals leave premiums out.",
                )
            )
        for w in p.doc.warnings:
            warnings.append(
                Warning(code=w.code, path=f"{k}:{w.path or ''}", message=f"Plan {k}: {w.message}")
            )

    result = ComparisonResult(
        engine_version=ENGINE_VERSION,
        reference_prices_version=prices.version,
        coverage_tier=req.coverage_tier,
        network=req.network,
        plans=refs,
        headline=headline,
        services=services,
        drug_tiers=drugs,
        coverage_gaps=gaps,
        scenarios=list(results.values()),
        ranked=ranked,
        reference_prices=prices.flat(),
        coverage_examples={k: p.coverage_examples for k, p in by_key.items()},
        warnings=warnings,
        assumptions=assumptions,
    )
    blob = json.dumps(result.model_dump(mode="json"), sort_keys=True).encode()
    result.result_hash = hashlib.sha256(blob).hexdigest()[:16]
    return result
