"""Comparison contracts: inputs (premiums, scenario) and the deterministic ComparisonResult that the
UI renders and the explanation LLM verbalizes. Every number the explanation may use is in here."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from sbcx.domain.benefits import Warning


class CoverageTier(str, Enum):
    individual = "individual"
    family = "family"


class Network(str, Enum):
    in_network = "in_network"
    out_of_network = "out_of_network"


class PlanInputs(BaseModel):
    monthly_premium: float | None = Field(None, ge=0, le=20000)
    employer_hsa_hra_annual: float = Field(0, ge=0, le=50000)


class Event(BaseModel):
    event: str
    count: int = Field(1, ge=1, le=365)
    member: int = Field(0, ge=0, le=9)


class Scenario(BaseModel):
    id: str
    label: str
    description: str = ""
    events: list[Event]


class Money(BaseModel):
    """A value that may be a range because the SBC leaves an input unknown."""

    low: float  # the result under the low-cost assumptions
    high: float  # under the high-cost assumptions (per claim, high can be below low once the cap is hit)

    @classmethod
    def exact(cls, v: float) -> "Money":
        return cls(low=v, high=v)


class Verdict(str, Enum):
    better = "better"
    worse = "worse"
    same = "same"
    not_comparable = "not_comparable"


class OverallVerdict(str, Enum):
    """Per-use verdict that accounts for the deductible: before and after it is met (v2.1 D1)."""

    better = "better"
    worse = "worse"
    same = "same"
    depends_on_deductible = "depends_on_deductible"
    not_comparable = "not_comparable"


class PlanRef(BaseModel):
    plan_key: str  # "A", "B", ... stable within one comparison
    document_id: str
    catalog_plan_id: str | None = None
    plan_name: str | None
    issuer: str | None
    plan_type: str | None
    metal: str | None = None
    is_base: bool


class AmountsView(BaseModel):
    individual: float | None
    family: float | None


class Headline(BaseModel):
    annual_premium: dict[str, float | None]
    employer_contribution: dict[str, float]
    deductible: dict[str, AmountsView | None]
    oop_limit: dict[str, AmountsView | None]
    best_case: dict[str, float | None]  # premiums - contribution
    worst_case: dict[str, float | None]  # + OOP limit for the coverage tier
    best_case_delta: dict[str, float | None]  # plan - base
    worst_case_delta: dict[str, float | None]


class CellView(BaseModel):
    display: str
    covered: bool | None
    copay: float | None = None
    coinsurance_pct: float | None = None
    deductible_applies: bool | None = None
    # applies | does_not_apply | applies_per_sbc | applies_hsa_rules | applies_catastrophic_rules |
    # before_per_sbc | not_stated | none
    deductible_status: str | None = None
    est_cost_per_use: float | None = None  # once the deductible is met
    est_cost_before_deductible: Money | None = None  # one use before the deductible is met (engine 1.3.0)
    note: str | None = None


class ServiceDiff(BaseModel):
    id: str
    service_key: str
    label: str
    section: str
    cells: dict[str, CellView]
    verdicts: dict[str, Verdict]  # non-base plan_key -> verdict vs base, after the deductible
    delta_per_use: dict[str, float | None]  # plan - base, estimated per use
    verdicts_before_deductible: dict[str, Verdict] = {}
    overall_verdicts: dict[str, OverallVerdict] = {}
    comparison_kind: Literal["exact", "estimated", "none"]
    reference_price: float | None
    flags: list[str] = []


class DrugTierDiff(BaseModel):
    id: str
    category: str
    label: str
    cells: dict[str, CellView | None]
    tier_names: dict[str, str | None]
    verdicts: dict[str, Verdict]
    delta_per_use: dict[str, float | None]
    reference_price: float | None
    verdicts_before_deductible: dict[str, Verdict] = {}
    overall_verdicts: dict[str, OverallVerdict] = {}


class LineItem(BaseModel):
    event: str
    service_key: str
    allowed: float
    member_pays: Money
    note: str = ""


class ScenarioPlanResult(BaseModel):
    annual_premium: float | None
    contribution: float
    out_of_pocket: Money
    total: Money
    deductible_met: bool
    oop_limit_met: bool
    trace: list[LineItem]
    assumptions: list[str] = []


class ScenarioResult(BaseModel):
    scenario: Scenario
    per_plan: dict[str, ScenarioPlanResult]
    cheapest: list[str]
    delta_vs_base: dict[str, Money]  # plan - base totals (low = best case for the plan)
    ranges_overlap: bool


class RankedDiff(BaseModel):
    diff_id: str
    label: str
    impact_usd: float
    severity: Literal["high", "medium", "low"]


class ComparisonProfile(BaseModel):
    """The details premiums were looked up with, kept so the builder can be restored and the result can say where
    premiums came from. The engine doesn't use it."""

    ages: list[int] = Field(default_factory=list, max_length=10)
    rating_areas: dict[str, str] = {}  # state -> CMS rating area, e.g. {"TX": "Rating Area 3"}

    @model_validator(mode="after")
    def _check(self) -> "ComparisonProfile":
        if any(a < 0 or a > 120 for a in self.ages):
            raise ValueError("ages must be between 0 and 120")
        if any(len(s) != 2 or len(a) > 32 for s, a in self.rating_areas.items()):
            raise ValueError("rating_areas maps a 2-letter state to a rating area name")
        return self


class ComparisonRequest(BaseModel):
    document_ids: list[str] = Field(min_length=2, max_length=5)
    base_document_id: str | None = None  # defaults to the first document
    inputs: dict[str, PlanInputs] = {}  # document_id -> inputs
    coverage_tier: CoverageTier = CoverageTier.individual
    network: Network = Network.in_network
    scenario_ids: list[str] = ["low", "moderate", "high"]
    custom_scenario: Scenario | None = None
    reference_price_overrides: dict[str, float] = {}
    explain: bool = True
    profile: ComparisonProfile | None = None

    @model_validator(mode="after")
    def _check(self) -> "ComparisonRequest":
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("document_ids must be unique")
        if self.base_document_id and self.base_document_id not in self.document_ids:
            raise ValueError("base_document_id must be one of document_ids")
        if any(v < 0 or v > 1_000_000 for v in self.reference_price_overrides.values()):
            raise ValueError("reference prices must be between 0 and 1,000,000")
        return self


class ComparisonResult(BaseModel):
    engine_version: str
    reference_prices_version: str
    coverage_tier: CoverageTier
    network: Network
    plans: list[PlanRef]
    headline: Headline
    services: list[ServiceDiff]
    drug_tiers: list[DrugTierDiff]
    coverage_gaps: list[str]
    scenarios: list[ScenarioResult]
    ranked: list[RankedDiff]
    reference_prices: dict[str, float]
    coverage_examples: dict[
        str, dict | None
    ] = {}  # plan_key -> SBC coverage examples (catalog plans, from the CMS PUF)
    warnings: list[Warning]
    assumptions: list[str]
    result_hash: str = ""
