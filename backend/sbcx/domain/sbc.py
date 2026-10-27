"""SBC extraction schema (v1 contract). Copied from src/schema.py; tests/unit/test_schema_drift.py
keeps the two identical. Design rationale: docs/03-schema.md

One schema drives three things, so it's defined once here:
  - teacher labeling:  sent to the teacher model as a JSON schema (structured outputs)
  - training targets:  the student learns to emit exactly this JSON
  - serving:           vLLM guided decoding via `SBCExtraction.model_json_schema()`
"""

from enum import Enum

from pydantic import BaseModel, Field

GUIDELINE_VERSION = "1.2"


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
- Fill BOTH copay and coinsurance_pct only when one charge combines them
  (e.g. "$250 copay then 20% coinsurance").
- Different prices for different parts of a service (e.g. "Office visit: $40 copay;
  other outpatient: 40% coinsurance", or "Physician: $60 copay; facility: 25%
  coinsurance") -> put the FIRST listed part in the structured fields and summarize
  the other parts in note. Never leave copay and coinsurance_pct both null when the
  document gives a price.
- Prices come from the price columns only. Text in the limitations column goes in
  note at most; it never overrides the price column.
- in_network is the standard in-network tier. Ignore special tiers such as
  Indian Health Care Providers (IHCP).
- out_of_network is null if the document says not applicable, unlimited, or gives no amount.
- note is only for terms the structured fields can't express (per-day copays,
  visit limits, "first 3 visits free"). At most 150 characters; otherwise null.
  Don't repeat prior-authorization or "balance billing may apply" boilerplate.
- drug_tiers: one entry per tier row in the SBC, in document order, retail
  30-day prices only. category=other if the tier fits none of the standard categories.
- services_before_deductible: services the SBC says are covered before you meet
  the deductible, as short names. Empty list if none.
- excluded_services: the "Services Your Plan Generally Does NOT Cover" list, as short names.
"""


# Guideline v1.3: TESTED, NOT ADOPTED (2026-10-17). It folds in the gold-review
# conventions, mainly a strict row-only rule for deductible_applies. On the gold set
# the teacher scored 96.5% with it vs 97.6% with v1.2-era prompting: it stopped
# inferring deductible flags for some insurers but started inferring them from
# legend marks for others. See docs/04-labeling.md. The gold set still follows
# these conventions; reproduce the run with `label_sbcs.py --guidelines 1.3`.
ANNOTATION_GUIDELINES_V1_3 = """\
General
- Extract only what the document states. Never infer from typical plans.
- Every key is always present. Use null for "not stated in the document".
- Money is a number in dollars (1500, not "$1,500"); percentages are 0-100.

Plan info
- issuer: the brand shown in the SBC header (e.g. "Ambetter Health"), not an
  underwriter named in the footer.
- plan_name: the plan name without an "Issuer:" prefix ("Oscar: Gold Elite Plan" -> "Gold Elite Plan").
- plan_type: exactly one of HMO, PPO, EPO, POS (drop market labels such as "IND").

Deductible and out-of-pocket limit
- "Single", "self-only", "per person", "individual" -> individual. The family amount may
  lack the word "family" (e.g. "$2,050 Individual / $4,100" -> family 4100).
- Plans with several in-network tiers: in_network = the first (lowest-cost) tier.
- out_of_network is null if the document says not applicable, unlimited, or gives no amount.

Cost-sharing cells
- "No charge"                 -> covered=true, copay=0, coinsurance_pct=0
- "Not covered"               -> covered=false, every other field null
- Fill BOTH copay and coinsurance_pct only when one charge combines them
  (e.g. "$250 copay then 20% coinsurance").
- Different prices for different parts of a service (e.g. "Office visit: $40 copay;
  other outpatient: 40% coinsurance", or "Physician: $60 copay; facility: 25%
  coinsurance") -> put the FIRST listed part in the structured fields and summarize
  the other parts in note. Sub-rows under one service (e.g. "Physician Visit" then
  "Emergency room") count as parts: the first sub-row goes in the structured fields.
  Never leave copay and coinsurance_pct both null when the document gives a price.
- Prices come from the price columns only. Text in the limitations column goes in
  note at most; it never overrides the price column.
- in_network is the first (lowest-cost) in-network column. Ignore special tiers such
  as Indian Health Care Providers (IHCP).

deductible_applies (decide from THAT ROW only)
- true:  the row's price cell or limitations cell says the deductible applies to the
  charge ("after deductible", "subject to deductible", "Coinsurance applies after deductible").
- false: the row says it doesn't ("deductible does not apply", "not subject to deductible",
  or a legend mark such as "†Deductible does not apply" next to the price).
- null:  the row says nothing about the deductible. Do NOT infer it from the page-1
  "services covered before you meet your deductible" list, from the chart-wide note
  "costs shown are after your deductible has been met, if a deductible applies", or
  from what other rows say. A plain "$25 copay" or "40% coinsurance" is null.

Notes and lists
- note is only for terms the structured fields can't express (per-day copays,
  visit limits, "first 3 visits free"). At most 150 characters; otherwise null.
  Don't repeat prior-authorization or "balance billing may apply" boilerplate.
- drug_tiers: one entry per tier in document order, retail 30-day prices only (skip
  separate mail-order rows). category=other if the tier fits none of the standard categories.
- services_before_deductible: services the SBC says are covered before you meet
  the deductible, as short names. Empty list if none.
- excluded_services: only the "Services Your Plan Generally Does NOT Cover" box, as short
  names. Never items from "Other Covered Services".
"""


class CostShare(BaseModel):
    covered: bool
    copay: float | None = Field(description="Dollar copay; 0 for 'No charge'")
    coinsurance_pct: float | None = Field(description="0-100; 0 for 'No charge'")
    deductible_applies: bool | None
    note: str | None = Field(max_length=150)


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


def normalize(label: SBCExtraction) -> SBCExtraction:
    """Deterministic fixes for conventions the teacher applies inconsistently.

    - "No charge" should be copay=0 AND coinsurance_pct=0, but the teacher often
      fills only one of them. Conversely, "$40 copay" must not get coinsurance_pct=0.
    - plan_type is one of HMO/PPO/EPO/POS ("IND POS" -> "POS").
    - plan_name drops an "Issuer:" prefix.
    Fixing these in code keeps every label consistent, which a prompt alone doesn't guarantee.
    """
    if label.plan_type:
        types = [t for t in ("HMO", "PPO", "EPO", "POS") if t in label.plan_type.upper().split()]
        if len(types) == 1:
            label.plan_type = types[0]
    if label.plan_name and label.issuer and ":" in label.plan_name:
        prefix, rest = label.plan_name.split(":", 1)
        if prefix.strip().lower() == label.issuer.strip().lower() and rest.strip():
            label.plan_name = rest.strip()
    cells = []
    for svc in [*label.services.__dict__.values(), *(t.retail for t in label.drug_tiers)]:
        cells += [svc.in_network, svc.out_of_network]
    for c in cells:
        if c is None or not c.covered:
            continue
        if c.copay == 0 and c.coinsurance_pct is None:
            c.coinsurance_pct = 0
        elif c.coinsurance_pct == 0 and c.copay is None:
            c.copay = 0
        # "$40 copay" is not "$40 copay then 0% coinsurance": a zero next to a real
        # price means "not applicable", which is null (the teacher writes 0 sometimes).
        elif c.copay and c.coinsurance_pct == 0:
            c.coinsurance_pct = None
        elif c.coinsurance_pct and c.copay == 0:
            c.copay = None
    return label
