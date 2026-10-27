"""The 13 benefit sections shown in the UI and summarized by the LLM (LLD §4.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sbcx.domain.benefits import BenefitsDocument
from sbcx.domain.display import DRUG_LABELS, SERVICE_LABELS, describe_cost, money


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


def section_input(doc: BenefitsDocument, sec: Section) -> dict[str, Any]:
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
                    "in_network": describe_cost(t.retail.in_network),
                    "out_of_network": describe_cost(t.retail.out_of_network),
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
                "in_network": describe_cost(svc.in_network),
                "out_of_network": describe_cost(svc.out_of_network),
                "note": svc.in_network.note if svc.in_network else None,
                "limitations": doc.extras.limitations.get(k, "")[:300] or None,
            }
        )
    return {"services": out}


def template_summary(doc: BenefitsDocument, sec: Section) -> tuple[str, list[str]]:
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
            f"{t.name}: {describe_cost(t.retail.in_network)}" for t in b.drug_tiers[:4]
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
        lines.append(f"{SERVICE_LABELS[k]}: {describe_cost(svc.in_network)} in network")
    return "; ".join(lines) + ".", []
