"""SBC extraction schema v1. Design rationale: docs/03-schema.md

One schema drives three things, so it's defined once here:
  - teacher labeling:  sent to the teacher model as a JSON schema (structured outputs)
  - training targets:  the student learns to emit exactly this JSON
  - serving:           vLLM guided decoding via `SBCExtraction.model_json_schema()`
"""

from enum import Enum

from pydantic import BaseModel, Field


# Given verbatim to the teacher model; also the rules a human follows when
# checking gold labels, so both label the same way.
ANNOTATION_GUIDELINES = """\
- Extract only what the document states. Never infer from typical plans.
- Every key is always present. Use null for "not stated in the document".
- Money is a number in dollars (1500, not "$1,500"); percentages are 0-100.
- "No charge"                 -> covered=true, copay=0, coinsurance_pct=0
- "Not covered"               -> covered=false, every other field null
- "deductible does not apply" -> deductible_applies=false
- "after deductible"          -> deductible_applies=true
- nothing said about it       -> deductible_applies=null
- Copay AND coinsurance both stated (e.g. "$250 copay then 20% coinsurance") -> fill both.
- in_network is the standard in-network tier. Ignore special tiers such as
  Indian Health Care Providers (IHCP).
- out_of_network is null if the document says not applicable, unlimited, or gives no amount.
- note is only for terms the structured fields can't express (per-day copays,
  visit limits, "first 3 visits free"). Keep it under 20 words; otherwise null.
- drug_tiers: one entry per tier row in the SBC, in document order, retail
  30-day prices only. category=other if the tier fits none of the standard categories.
- services_before_deductible: services the SBC says are covered before you meet
  the deductible, as short names. Empty list if none.
- excluded_services: the "Services Your Plan Generally Does NOT Cover" list, as short names.
"""


class CostShare(BaseModel):
    covered: bool
    copay: float | None = Field(description="Dollar copay; 0 for 'No charge'")
    coinsurance_pct: float | None = Field(description="0-100; 0 for 'No charge'")
    deductible_applies: bool | None
    note: str | None


class ServiceCost(BaseModel):
    in_network: CostShare | None
    out_of_network: CostShare | None


class Amounts(BaseModel):
    individual: float | None
    family: float | None


class NetworkAmounts(BaseModel):
    in_network: Amounts | None
    out_of_network: Amounts | None = Field(description="null if not applicable or unlimited")


class DrugCategory(str, Enum):
    generic = "generic"
    preferred_brand = "preferred_brand"
    non_preferred_brand = "non_preferred_brand"
    specialty = "specialty"
    other = "other"


class DrugTier(BaseModel):
    name: str = Field(description="Tier label as written in the SBC, e.g. 'Tier 1 - Generic'")
    category: DrugCategory
    retail: ServiceCost = Field(description="Retail pharmacy, 30-day supply")


class Services(BaseModel):
    # "If you visit a health care provider's office or clinic"
    primary_care_visit: ServiceCost
    specialist_visit: ServiceCost
    preventive_care: ServiceCost
    # "If you have a test"
    diagnostic_test: ServiceCost
    imaging: ServiceCost
    # "If you have outpatient surgery"
    outpatient_facility_fee: ServiceCost
    outpatient_surgeon_fee: ServiceCost
    # "If you need immediate medical attention"
    emergency_room: ServiceCost
    emergency_transportation: ServiceCost
    urgent_care: ServiceCost
    # "If you have a hospital stay"
    hospital_facility_fee: ServiceCost
    hospital_surgeon_fee: ServiceCost
    # "If you need mental health, behavioral health, or substance abuse services"
    mental_health_outpatient: ServiceCost
    mental_health_inpatient: ServiceCost
    # "If you are pregnant"
    pregnancy_office_visits: ServiceCost
    childbirth_professional: ServiceCost
    childbirth_facility: ServiceCost
    # "If you need help recovering or have other special health needs"
    home_health_care: ServiceCost
    rehabilitation: ServiceCost
    habilitation: ServiceCost
    skilled_nursing: ServiceCost
    durable_medical_equipment: ServiceCost
    hospice: ServiceCost
    # "If your child needs dental or eye care"
    child_eye_exam: ServiceCost
    child_glasses: ServiceCost
    child_dental_checkup: ServiceCost


class SBCExtraction(BaseModel):
    plan_name: str | None
    issuer: str | None
    plan_type: str | None = Field(description="HMO, PPO, EPO, POS, ...")
    coverage_period: str | None = Field(description="e.g. '01/01/2026 - 12/31/2026'")
    deductible: NetworkAmounts
    out_of_pocket_limit: NetworkAmounts
    services_before_deductible: list[str]
    referral_required_for_specialist: bool | None
    services: Services
    drug_tiers: list[DrugTier]
    excluded_services: list[str]
