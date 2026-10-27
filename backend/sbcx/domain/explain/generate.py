"""Explanation of a comparison (LLD §6). The LLM sees only a fact sheet derived from the computed
ComparisonResult; every number it writes must be in that fact sheet. One retry with the violations
listed, then a deterministic template explanation."""

from __future__ import annotations

import json
import re
from typing import Any

from sbcx.domain.comparison import ComparisonResult, Money
from sbcx.domain.display import money
from sbcx.domain.explain.grounding import check, collect
from sbcx.domain.explanation import Explanation, ExplanationRecord, GroundingReport, ScenarioText
from sbcx.infra.llm.base import LLMClient, LLMError
from sbcx.versions import EXPLANATION_PROMPT_VERSION

DISCLAIMER = (
    "These are estimates from the plans' Summary of Benefits and Coverage documents and reference prices, "
    "not a quote or advice. Check the plan documents and your providers before you decide."
)

SYSTEM = """You explain a comparison of US health insurance plans to a non-expert, using ONLY the FACTS JSON.
Rules:
- Every dollar amount, percentage and number you write must appear in FACTS exactly (you may round to whole dollars).
  Never add, subtract or compute new numbers: FACTS already contains every total and difference you need.
- Refer to plans by their name (or "Plan A", "Plan B" as given).
- When a scenario's ranges overlap ("ranges_overlap": true), say the result depends and why (usually the
  deductible isn't stated for some services). Don't call one plan cheaper in that case.
- Mention coverage gaps (a service one plan doesn't cover) in watch_out.
- Neutral and factual. Never tell the reader which plan to choose ("you should", "we recommend", "best plan for you").
  Never promise savings ("you will save").
- headline: one sentence, at most 25 words. key_points: 3-5 short sentences. scenarios: one short paragraph per
  scenario in FACTS. watch_out: up to 5 items. assumptions: up to 4 short items. disclaimer: one sentence."""

BANNED = re.compile(
    r"(?i)\b(you should|we recommend|i recommend|recommended plan|best plan for you|you will save|guarantee[ds]?|"
    r"definitely choose|must choose|go with plan)\b"
)


def _m(v: Money) -> Any:
    return v.low if v.low == v.high else {"low": v.low, "high": v.high}


def factsheet(
    result: ComparisonResult, summaries: dict[str, dict[str, str]] | None = None, top_k: int = 8
) -> dict[str, Any]:
    names = {p.plan_key: (p.plan_name or f"Plan {p.plan_key}") for p in result.plans}
    h = result.headline
    diffs = {d.id: d for d in result.services} | {d.id: d for d in result.drug_tiers}
    top = []
    for r in result.ranked[:top_k]:
        d = diffs[r.diff_id]
        top.append(
            {
                "id": d.id,
                "item": d.label,
                "impact_estimate": r.impact_usd,
                "severity": r.severity,
                "per_plan": {
                    k: {
                        "cost_sharing": (c.display if c else "not listed"),
                        "estimated_cost_per_use": (c.est_cost_per_use if c else None),
                    }
                    for k, c in d.cells.items()
                },
                "difference_per_use_vs_base": d.delta_per_use,
                "reference_price": d.reference_price,
            }
        )
    scen = []
    for s in result.scenarios:
        scen.append(
            {
                "scenario": s.scenario.label,
                "description": s.scenario.description,
                "annual_total": {k: _m(r.total) for k, r in s.per_plan.items()},
                "out_of_pocket": {k: _m(r.out_of_pocket) for k, r in s.per_plan.items()},
                "difference_vs_base": {k: _m(v) for k, v in s.delta_vs_base.items()},
                "lowest_cost": [names[k] for k in s.cheapest],
                "ranges_overlap": s.ranges_overlap,
            }
        )
    base = next(p.plan_key for p in result.plans if p.is_base)
    return {
        "plans": [
            {
                "key": p.plan_key,
                "name": names[p.plan_key],
                "issuer": p.issuer,
                "type": p.plan_type,
                "metal": p.metal,
                "is_base": p.is_base,
            }
            for p in result.plans
        ],
        "base_plan": names[base],
        "coverage": result.coverage_tier.value,
        "network": result.network.value,
        "headline": {
            "annual_premium": h.annual_premium,
            "employer_contribution": h.employer_contribution,
            "deductible": {k: (v.model_dump() if v else None) for k, v in h.deductible.items()},
            "out_of_pocket_limit": {k: (v.model_dump() if v else None) for k, v in h.oop_limit.items()},
            "best_case_no_care": h.best_case,
            "worst_case_max_out_of_pocket": h.worst_case,
            "best_case_difference_vs_base": h.best_case_delta,
            "worst_case_difference_vs_base": h.worst_case_delta,
        },
        "scenarios": scen,
        "top_differences": top,
        "coverage_gaps": [diffs[g].label for g in result.coverage_gaps][:6],
        "section_summaries": summaries or {},
        "warnings": [
            w.message
            for w in result.warnings
            if w.code
            in ("W_PREMIUM_MISSING", "W_FALLBACK_OVERRIDE", "W_LOW_ANCHOR_COVERAGE", "W_NO_OOP_FOUND")
        ][:6],
        "assumptions": result.assumptions[:6],
    }


def _validate(e: Explanation, facts: dict) -> GroundingReport:
    texts = [e.headline, *e.key_points, *(s.text for s in e.scenarios), *e.watch_out, *e.assumptions]
    n, bad = check(texts, collect(facts))
    policy = sorted({m.group(0) for t in texts for m in BANNED.finditer(t)})
    return GroundingReport(
        ok=not bad and not policy, numbers_checked=n, violations=bad, policy_violations=policy
    )


def _fmt(v: Any) -> str:
    if isinstance(v, dict):
        return f"{money(v['low'])}–{money(v['high'])}"
    return money(v)


def template_explanation(facts: dict) -> Explanation:
    """Built only from fact-sheet values, so it is grounded by construction."""
    names = {p["key"]: p["name"] for p in facts["plans"]}
    base = facts["base_plan"]
    h = facts["headline"]
    points = []
    for k, name in names.items():
        d = (h["deductible"].get(k) or {}).get("individual")
        o = (h["out_of_pocket_limit"].get(k) or {}).get("individual")
        prem = h["annual_premium"].get(k)
        bits = [
            f"deductible {money(d)}" if d is not None else "deductible not stated",
            f"out-of-pocket limit {money(o)}" if o is not None else "no out-of-pocket limit found",
        ]
        if prem is not None:
            bits.insert(0, f"premiums {money(prem)} a year")
        points.append(f"{name}: " + ", ".join(bits) + ".")
    scen_texts = []
    for s in facts["scenarios"]:
        totals = "; ".join(f"{names[k]} {_fmt(v)}" for k, v in s["annual_total"].items())
        if s["ranges_overlap"]:
            verdict = "The ranges overlap, so which plan costs less depends on details the SBCs don't state."
        else:
            verdict = f"Lowest estimated total: {', '.join(s['lowest_cost'])}."
        scen_texts.append(
            ScenarioText(scenario=s["scenario"], text=f"Estimated yearly total: {totals}. {verdict}")
        )
    lowest = facts["scenarios"][0]["lowest_cost"] if facts["scenarios"] else []
    headline = (
        f"Compared with {base}, the plans differ most in "
        + ", ".join(t["item"].lower() for t in facts["top_differences"][:2])
        + "."
        if facts["top_differences"]
        else f"Here is how the plans compare with {base}."
    )
    watch = [f"Not covered by every plan: {g}." for g in facts["coverage_gaps"][:3]] + facts["warnings"][:2]
    _ = lowest
    return Explanation(
        headline=headline,
        key_points=points[:5] or ["No differences were found."],
        scenarios=scen_texts,
        watch_out=watch[:5],
        assumptions=facts["assumptions"][:4],
        disclaimer=DISCLAIMER,
    )


def explain(
    result: ComparisonResult,
    llm: LLMClient | None,
    model: str,
    summaries: dict[str, dict[str, str]] | None = None,
) -> ExplanationRecord:
    facts = factsheet(result, summaries)
    user = "FACTS:\n" + json.dumps(facts, ensure_ascii=False)
    if llm is not None:
        prompt = user
        for attempt in range(2):
            try:
                r = llm.complete_json(
                    task="explanation",
                    system=SYSTEM,
                    user=prompt,
                    schema=Explanation,
                    model=model,
                    max_tokens=1500,
                )
            except LLMError:
                break
            e = Explanation.model_validate(r.data)
            e.disclaimer = DISCLAIMER
            rep = _validate(e, facts)
            if rep.ok:
                return ExplanationRecord(
                    content=e,
                    source="llm" if attempt == 0 else "llm_retry",
                    grounding=rep,
                    model=r.model,
                    prompt_version=EXPLANATION_PROMPT_VERSION,
                )
            problems = [f"numbers not in FACTS: {', '.join(rep.violations)}"] if rep.violations else []
            if rep.policy_violations:
                problems.append(f"advice/guarantee wording not allowed: {', '.join(rep.policy_violations)}")
            prompt = (
                user + "\n\nYour previous answer broke the rules (" + "; ".join(problems) + "). Rewrite it."
            )
    e = template_explanation(facts)
    return ExplanationRecord(
        content=e, source="template", grounding=_validate(e, facts), prompt_version=EXPLANATION_PROMPT_VERSION
    )


def fake_explanation(system: str, user: str) -> dict:
    facts = json.loads(user.split("FACTS:\n", 1)[1].split("\n\nYour previous", 1)[0])
    return template_explanation(facts).model_dump()
