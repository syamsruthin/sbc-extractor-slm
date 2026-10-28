"""Human wording for structured values, shared by templates, the UI payload and the LLM inputs."""

from __future__ import annotations

from sbcx.domain.sbc import CostShare

SERVICE_LABELS = {
    "primary_care_visit": "Primary care visit",
    "specialist_visit": "Specialist visit",
    "preventive_care": "Preventive care / screening",
    "diagnostic_test": "Diagnostic test (x-ray, blood work)",
    "imaging": "Imaging (CT/PET, MRI)",
    "outpatient_facility_fee": "Outpatient surgery facility fee",
    "outpatient_surgeon_fee": "Outpatient surgery physician/surgeon fee",
    "emergency_room": "Emergency room care",
    "emergency_transportation": "Emergency medical transportation",
    "urgent_care": "Urgent care",
    "hospital_facility_fee": "Hospital stay facility fee",
    "hospital_surgeon_fee": "Hospital stay physician/surgeon fee",
    "mental_health_outpatient": "Mental/behavioral health outpatient",
    "mental_health_inpatient": "Mental/behavioral health inpatient",
    "pregnancy_office_visits": "Pregnancy office visits",
    "childbirth_professional": "Childbirth/delivery professional services",
    "childbirth_facility": "Childbirth/delivery facility services",
    "home_health_care": "Home health care",
    "rehabilitation": "Rehabilitation services",
    "habilitation": "Habilitation services",
    "skilled_nursing": "Skilled nursing care",
    "durable_medical_equipment": "Durable medical equipment",
    "hospice": "Hospice services",
    "child_eye_exam": "Children's eye exam",
    "child_glasses": "Children's glasses",
    "child_dental_checkup": "Children's dental check-up",
}

DRUG_LABELS = {
    "generic": "Generic drugs",
    "preferred_brand": "Preferred brand drugs",
    "non_preferred_brand": "Non-preferred brand drugs",
    "specialty": "Specialty drugs",
    "other": "Other drug tier",
}


def money(v: float | None) -> str:
    if v is None:
        return "unknown"
    return f"${v:,.0f}" if float(v).is_integer() else f"${v:,.2f}"


def pct(v: float) -> str:
    return f"{v:g}%"


DEDUCTIBLE_TEXT = {
    "applies": ", after deductible",
    "does_not_apply": ", deductible doesn't apply",
    "applies_per_sbc": ", after deductible (per the SBC's page 1)",
    "applies_hsa_rules": ", after deductible (HSA plan rules)",
    "applies_catastrophic_rules": ", after deductible (catastrophic plan rules)",
    "first_visits_before": ", deductible doesn't apply to the first 3 visits (catastrophic plan rules)",
    "before_per_sbc": ", deductible doesn't apply",
    "not_stated": ", deductible not stated",
    "none": "",
}


def describe_cost(c: CostShare | None, with_deductible: bool = True, status: str | None = None) -> str:
    if c is None:
        return "Not listed"
    if not c.covered:
        return "Not covered"
    parts = []
    if c.copay == 0 and c.coinsurance_pct == 0:
        parts.append("No charge")
    else:
        if c.copay is not None:
            parts.append(f"{money(c.copay)} copay")
        if c.coinsurance_pct is not None:
            parts.append(f"{pct(c.coinsurance_pct)} coinsurance")
    text = " then ".join(parts) if parts else "Covered (price not stated)"
    if with_deductible and status is not None:
        return text + DEDUCTIBLE_TEXT[status]
    if with_deductible:
        if c.deductible_applies is True:
            text += ", after deductible"
        elif c.deductible_applies is False:
            text += ", deductible doesn't apply"
    return text
