"""Request/response DTOs for the HTTP API. Domain contracts (BenefitsDocument, ComparisonResult,
Explanation) are returned as-is inside these envelopes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, Field

from sbcx.domain.benefits import BenefitsDocument, FieldMeta
from sbcx.domain.comparison import ComparisonRequest, ComparisonResult, Scenario
from sbcx.domain.explanation import ExplanationRecord

# SQLite returns naive datetimes; everything is stored in UTC, so label it as such for clients.
UTCDateTime = Annotated[datetime, AfterValidator(lambda d: d if d.tzinfo else d.replace(tzinfo=UTC))]

DocStatus = Literal["queued", "extracting", "ready", "failed"]
TaskStatus = Literal["pending", "running", "ready", "skipped", "failed"]


class DocumentSummary(BaseModel):
    id: str
    filename: str
    source: str
    status: DocStatus
    error_code: str | None = None
    error_message: str | None = None
    plan_name: str | None = None
    issuer: str | None = None
    plan_type: str | None = None
    npages: int | None = None
    doc_confidence: float | None = None
    summaries_status: TaskStatus
    warning_count: int = 0
    catalog_plan_id: str | None = None
    created_at: UTCDateTime


class DocumentDetail(DocumentSummary):
    benefits: BenefitsDocument | None = None
    # deductible wording per cost cell, using the same rules as comparisons (catalog metal/HSA flag included)
    deductible_notes: dict[str, str] = Field(default_factory=dict)


class DocumentList(BaseModel):
    items: list[DocumentSummary]


class Provenance(BaseModel):
    path: str
    value: Any
    meta: FieldMeta | None


class CatalogPlan(BaseModel):
    plan_id: str
    plan_year: int
    state: str
    issuer: str
    plan_name: str
    metal: str | None
    plan_type: str | None
    document_id: str | None
    deductible_individual: float | None
    oop_individual: float | None


class CatalogPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[CatalogPlan]


class FacetValue(BaseModel):
    value: str
    count: int


class CatalogFacets(BaseModel):
    state: list[FacetValue]
    metal: list[FacetValue]
    plan_type: list[FacetValue]
    issuer: list[FacetValue]
    premiums_loaded: bool


class PremiumQuote(BaseModel):
    plan_id: str
    age: str
    rating_area: str
    monthly_premium: float


class PremiumQuotes(BaseModel):
    items: list[PremiumQuote]


class ComparisonResponse(BaseModel):
    id: str
    created_at: UTCDateTime
    request: ComparisonRequest
    result: ComparisonResult
    explanation_status: TaskStatus
    explanation: ExplanationRecord | None = None


class ComparisonListItem(BaseModel):
    id: str
    created_at: UTCDateTime
    plan_names: list[str]


class ScenarioCatalog(BaseModel):
    presets: list[Scenario]
    event_types: dict[str, dict[str, Any]]


class ReferencePrices(BaseModel):
    version: str
    source: str
    prices: dict[str, float]
    labels: dict[str, str]


class UsageStats(BaseModel):
    llm: dict[str, dict[str, Any]]
