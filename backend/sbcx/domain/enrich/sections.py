"""The 13 benefit sections shown in the UI and summarized by the LLM (LLD §4.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sbcx.domain.benefits import BenefitsDocument
from sbcx.domain.display import DRUG_LABELS, SERVICE_LABELS, describe_cost, money
from sbcx.domain.sbc import CostShare

if TYPE_CHECKING:
    from sbcx.domain.compare.cost_model import DeductibleHints


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    services: tuple[str, ...] = ()


SECTIONS = [
    Section("overview", "Plan overview"),
    Section("deductible_oop", "Deductible and out-of-pocket limit"),
    Section("office_visits", "Doctor visits", ("primary_care_visit", "specialist_visit", "preventive_care")),
    Section("tests", "Tests", ("diagnostic_test", "imaging")),
    Section("drugs", "Prescription drugs"),
    Section(
        "outpatient_surgery", "Outpatient surgery", ("outpatient_facility_fee", "outpatient_surgeon_fee")
    ),
    Section(
        "emergency",
        "Emergency and urgent care",
        ("emergency_room", "emergency_transportation", "urgent_care"),
    ),
    Section("hospital", "Hospital stay", ("hospital_facility_fee", "hospital_surgeon_fee")),
    Section(
        "mental_health",
        "Mental health and substance use",
        ("mental_health_outpatient", "mental_health_inpatient"),
    ),
    Section(
        "pregnancy",
        "Pregnancy",
        ("pregnancy_office_visits", "childbirth_professional", "childbirth_facility"),
    ),
    Section(
        "recovery",
        "Recovery and special needs",
        (
            "home_health_care",
            "rehabilitation",
            "habilitation",
            "skilled_nursing",
            "durable_medical_equipment",
            "hospice",
        ),
    ),
    Section(
        "children",
        "Children's eye and dental care",
        ("child_eye_exam", "child_glasses", "child_dental_checkup"),
    ),
    Section("exclusions", "Services not covered"),
]
SECTION_BY_ID = {s.id: s for s in SECTIONS}
SERVICE_SECTION = {k: s.id for s in SECTIONS for k in s.services}


def _amounts(a) -> dict | None:
    return None if a is None else {"individual": a.individual, "family": a.family}


def cell_text(
    doc: BenefitsDocument,
    hints: DeductibleHints | None,
    cs: CostShare | None,
    key: str,
    network: str = "in_network",
) -> str:
    """describe_cost with an explicit deductible status (so "not stated" never reads as "no deductible").
    `hints` should be the ones the comparison uses (catalog metal/HSA flag); None = the document alone."""
    from sbcx.domain.compare.cost_model import deductible_hints, deductible_status, has_deductible
    from sbcx.domain.comparison import Network

    h = hints or deductible_hints(doc.benefits)
    return describe_cost(
        cs, status=deductible_status(cs, key, h, has_deductible(doc.benefits, Network(network)))
    )


def deductible_notes(doc: BenefitsDocument, hints: DeductibleHints | None = None) -> dict[str, str]:
    """Deductible wording for every cost cell, keyed by provenance-style path ("services.imaging.in_network",
    "drug_tiers[0].retail.in_network"); cells that need no note are left out."""
    from sbcx.domain.compare.cost_model import deductible_hints, deductible_status, has_deductible
    from sbcx.domain.comparison import Network
    from sbcx.domain.display import DEDUCTIBLE_TEXT

    b = doc.benefits
    h = hints or deductible_hints(b)
    cells: list[tuple[str, CostShare | None, str, str]] = []
    for k in SERVICE_SECTION:
        svc = getattr(b.services, k)
        cells += [(f"services.{k}.{n}", getattr(svc, n), k, n) for n in ("in_network", "out_of_network")]
    for i, t in enumerate(b.drug_tiers):
        key = f"drug:{t.category.value}"
        cells += [
            (f"drug_tiers[{i}].retail.{n}", getattr(t.retail, n), key, n)
            for n in ("in_network", "out_of_network")
        ]
    has = {n: has_deductible(b, Network(n)) for n in ("in_network", "out_of_network")}
    out = {}
    for path, cs, key, n in cells:
        if cs is None or not cs.covered:
            continue
        note = DEDUCTIBLE_TEXT[deductible_status(cs, key, h, has[n])].removeprefix(", ")
        if note:
            out[path] = note
    return out


def section_input(
    doc: BenefitsDocument, sec: Section, hints: DeductibleHints | None = None
) -> dict[str, Any]:
    """Compact, human-labeled facts for one section: the only input the summarizer sees."""
    b = doc.benefits
    if sec.id == "overview":
        return {
            "plan_name": b.plan_name,
            "issuer": b.issuer,
            "plan_type": b.plan_type,
            "coverage_period": b.coverage_period,
            "referral_required_for_specialist": b.referral_required_for_specialist,
        }
    if sec.id == "deductible_oop":
        return {
            "deductible": {
                "in_network": _amounts(b.deductible.in_network),
                "out_of_network": _amounts(b.deductible.out_of_network),
            },
            "out_of_pocket_limit": {
                "in_network": _amounts(b.out_of_pocket_limit.in_network),
                "out_of_network": _amounts(b.out_of_pocket_limit.out_of_network),
            },
            "family_deductible_type": doc.extras.deductible_type.value,
            "services_covered_before_deductible": b.services_before_deductible,
        }
    if sec.id == "drugs":
        return {
            "tiers": [
                {
                    "name": t.name,
                    "category": DRUG_LABELS[t.category.value],
                    "in_network": cell_text(doc, hints, t.retail.in_network, f"drug:{t.category.value}"),
                    "out_of_network": cell_text(
                        doc, hints, t.retail.out_of_network, f"drug:{t.category.value}", "out_of_network"
                    ),
                    "note": (t.retail.in_network.note if t.retail.in_network else None),
                }
                for t in b.drug_tiers
            ],
            "limitations": (doc.extras.drug_limitations or "")[:400],
        }
    if sec.id == "exclusions":
        return {"not_covered": b.excluded_services}
    out = []
    for k in sec.services:
        svc = getattr(b.services, k)
        out.append(
            {
                "service": SERVICE_LABELS[k],
                "in_network": cell_text(doc, hints, svc.in_network, k),
                "out_of_network": cell_text(doc, hints, svc.out_of_network, k, "out_of_network"),
                "note": svc.in_network.note if svc.in_network else None,
                "limitations": doc.extras.limitations.get(k, "")[:300] or None,
            }
        )
    return {"services": out}


def template_summary(
    doc: BenefitsDocument, sec: Section, hints: DeductibleHints | None = None
) -> tuple[str, list[str]]:
    """Deterministic fallback text built from the same facts (always grounded)."""
    b = doc.benefits
    if sec.id == "overview":
        bits = [x for x in (b.issuer, b.plan_name) if x]
        s = f"{' – '.join(bits) or 'This plan'} is a{'n' if (b.plan_type or 'P')[0] in 'AEIOU' else ''} {b.plan_type or 'health'} plan."
        if b.referral_required_for_specialist is not None:
            s += (
                " You need a referral to see a specialist."
                if b.referral_required_for_specialist
                else " You don't need a referral to see a specialist."
            )
        return s, []
    if sec.id == "deductible_oop":
        d, o = b.deductible.in_network, b.out_of_pocket_limit.in_network
        s = (
            f"In network, the deductible is {money(d.individual) if d else 'not stated'} for an individual"
            f"{f' and {money(d.family)} for a family' if d and d.family else ''}. "
        )
        s += (
            f"The most you pay in a year for covered in-network care is {money(o.individual) if o else 'not stated'}"
            f"{f' ({money(o.family)} for a family)' if o and o.family else ''}."
        )
        return s, []
    if sec.id == "drugs":
        if not b.drug_tiers:
            return "No prescription drug tiers were found in this document.", []
        return "; ".join(
            f"{t.name}: {cell_text(doc, hints, t.retail.in_network, f'drug:{t.category.value}')}"
            for t in b.drug_tiers[:4]
        ) + ".", []
    if sec.id == "exclusions":
        if not b.excluded_services:
            return "The document lists no excluded services.", []
        return "Not covered: " + ", ".join(b.excluded_services[:8]) + (
            "…" if len(b.excluded_services) > 8 else "."
        ), []
    lines = []
    for k in sec.services:
        svc = getattr(b.services, k)
        lines.append(f"{SERVICE_LABELS[k]}: {cell_text(doc, hints, svc.in_network, k)} in network")
    return "; ".join(lines) + ".", []
