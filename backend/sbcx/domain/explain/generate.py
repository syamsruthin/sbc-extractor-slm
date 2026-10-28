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
- For any "lowest/highest/cheapest" statement about premiums, deductibles, out-of-pocket limits, the no-care
  (best) case or the worst case, use FACTS.rankings; for scenario totals use scenarios[].lowest_cost. Don't infer
  rankings yourself.
- "deductible not stated" means the SBC doesn't say: never call that service free or say it skips the deductible.
  "No charge, after deductible" is free only once the deductible is met.
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


def rankings(
    metrics: dict[str, dict[str, float | None]], names: dict[str, str]
) -> dict[str, dict[str, list[str]]]:
    """Which plans are lowest/highest on each headline metric (ties included), so the LLM never has to infer it.
    The *_keys lists hold plan letters: claim checks use them because plan names can repeat (CSR variants)."""
    out = {}
    for m, vals in metrics.items():
        known = {k: v for k, v in vals.items() if v is not None}
        if len(known) < 2:
            continue
        lo, hi = min(known.values()), max(known.values())
        lo_k = [k for k, v in known.items() if v == lo]
        hi_k = [k for k, v in known.items() if v == hi]
        out[m] = {
            "lowest": [names[k] for k in lo_k],
            "highest": [names[k] for k in hi_k],
            "lowest_keys": lo_k,
            "highest_keys": hi_k,
        }
    return out


_SUPER = re.compile(r"(?i)\b(lowest|cheapest|least expensive|smallest|highest|most expensive|largest)\b")
_HEDGE = re.compile(r"(?i)\b(depends?|depending|overlap\w*|may|might|could|unclear|uncertain)\b")
_METRIC = [
    ("worst_case_max_out_of_pocket", re.compile(r"(?i)worst[- ]case")),
    ("best_case_no_care", re.compile(r"(?i)best[- ]case|no care|use no care|without care")),
    ("out_of_pocket_limit", re.compile(r"(?i)out[- ]of[- ]pocket (limit|max)|\boop\b|maximum out")),
    ("deductible", re.compile(r"(?i)deductible")),
    ("annual_premium", re.compile(r"(?i)premium")),
]


def _mentions(text: str, facts: dict) -> list[tuple[int, str]]:
    """(position, plan key) for plan names, "Plan X" letters and unique metal names mentioned in text."""
    plans = facts["plans"]
    found: list[tuple[int, str]] = []
    for p in plans:
        if sum(q["name"] == p["name"] for q in plans) == 1:  # a repeated name doesn't identify a plan
            for m in re.finditer(re.escape(p["name"]), text):
                found.append((m.start(), p["key"]))
        for m in re.finditer(rf"\bPlans? {p['key']}\b|\b(?<=and ){p['key']}\b(?=\W)", text):
            found.append((m.start(), p["key"]))
    metals = [p.get("metal") for p in plans]
    for p in plans:
        mt = p.get("metal")
        if mt and metals.count(mt) == 1:
            word = mt.split()[-1]
            for m in re.finditer(rf"\b{re.escape(word)}\b", text):
                found.append((m.start(), p["key"]))
    return sorted(set(found))


def claim_check(e: Explanation, facts: dict) -> list[str]:
    """Superlative claims ("X has the lowest deductible") must agree with FACTS.rankings / lowest_cost."""
    bad = []
    rank = facts.get("rankings", {})
    scen = {s["scenario"]: s for s in facts["scenarios"]}
    pieces = [(None, t) for t in (e.headline, *e.key_points, *e.watch_out)] + [
        (s.scenario, s.text) for s in e.scenarios
    ]
    for scenario, text in pieces:
        for sent in re.split(r"(?<=[.!?;])\s+", text):
            if _HEDGE.search(sent):  # "the lowest cost depends on ...", "ranges overlap" are not claims
                continue
            sups = list(_SUPER.finditer(sent))
            ments = _mentions(sent, facts)
            for i, sup in enumerate(sups):
                kind = (
                    "lowest"
                    if sup.group(1).lower() in ("lowest", "cheapest", "least expensive", "smallest")
                    else "highest"
                )
                # each superlative is checked against the nearest metric before the next superlative
                stop = sups[i + 1].start() if i + 1 < len(sups) else len(sent)
                after = sent[sup.end() : min(stop, sup.end() + 60)]
                hits = [(m.start(), name) for name, rx in _METRIC if (m := rx.search(after))]
                metric = min(hits)[1] if hits else None
                before = [n for pos, n in ments if pos < sup.start()]
                subject = before[-1:] if before else [n for pos, n in ments][:1]
                if re.search(r"(?i)\bplans\s+\w+\s+and\s+\w+", sent[: sup.start()]):
                    subject = sorted({n for pos, n in ments if pos < sup.start()})
                if not subject:
                    continue
                if metric and metric in rank:
                    truth = rank[metric][f"{kind}_keys"]
                    if not set(subject) <= set(truth):
                        bad.append(
                            f'"{sent.strip()}" — {kind} {metric.replace("_", " ")}: {", ".join(rank[metric][kind])}'
                        )
                elif (
                    metric is None
                    and kind == "lowest"
                    and scenario in scen
                    and before  # "X has the lowest total"; a plan named only after the word is not its subject
                    and re.search(r"(?i)total|cost", after)
                ):
                    s = scen[scenario]
                    if s["ranges_overlap"] and len(subject) == 1:
                        bad.append(f'"{sent.strip()}" — ranges overlap in {scenario}; no single lowest plan')
                    elif not set(subject) <= set(s["lowest_cost_keys"]):
                        bad.append(f'"{sent.strip()}" — lowest in {scenario}: {", ".join(s["lowest_cost"])}')
    return bad


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
                "lowest_cost_keys": list(s.cheapest),
                "ranges_overlap": s.ranges_overlap,
            }
        )
    base = next(p.plan_key for p in result.plans if p.is_base)
    deductible_part = "family" if result.coverage_tier.value == "family" else "individual"
    metrics = {
        "annual_premium": h.annual_premium,
        "deductible": {
            k: (v.family if deductible_part == "family" and v.family is not None else v.individual)
            if v
            else None
            for k, v in h.deductible.items()
        },
        "out_of_pocket_limit": {
            k: (v.family if deductible_part == "family" and v.family is not None else v.individual)
            if v
            else None
            for k, v in h.oop_limit.items()
        },
        "best_case_no_care": h.best_case,
        "worst_case_max_out_of_pocket": h.worst_case,
    }
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
        "rankings": rankings(metrics, names),
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
    claims = claim_check(e, facts)
    return GroundingReport(
        ok=not bad and not policy and not claims,
        numbers_checked=n,
        violations=bad,
        policy_violations=policy,
        claim_violations=claims,
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
            if rep.claim_violations:
                problems.append(
                    "claims that contradict FACTS.rankings or scenarios[].lowest_cost: "
                    + "; ".join(rep.claim_violations)
                )
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
