"""SBC extraction schema v1. Design rationale: docs/03-schema.md

One schema drives three things, so it's defined once here:
  - teacher labeling:  passed to Gemini as `response_schema`
  - training targets:  the student learns to emit exactly this JSON
  - serving:           vLLM guided decoding via `SBCExtraction.model_json_schema()`

Conventions (these are also the annotation guidelines given to the teacher model):
  - Every key is always present. Use null for "not stated in the document",
    never omit a key. A fixed shape keeps evaluation and guided decoding simple.
  - Money is a number in dollars (1500, not "$1,500"); percentages are 0-100.
  - "No charge"                -> covered=true, copay=0, coinsurance_pct=0
  - "Not covered"              -> covered=false, every other field null
  - "deductible does not apply"-> deductible_applies=false
  - "after deductible"         -> deductible_applies=true
  - nothing said about it      -> deductible_applies=null
  - `in_network` = the standard in-network tier. Special tiers such as
    Indian Health Care Providers are ignored in v1.
  - `note` is only for terms the structured fields can't express (per-day
    copays, visit limits, "first 3 visits free"). Keep it short; otherwise null.
"""

from enum import Enum

from pydantic import BaseModel, Field


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
