"""BenefitsDocument v2: the extraction contract. `benefits` is the unchanged v1 SBCExtraction, so
eval/score.py and the existing labels keep working; everything new lives next to it."""

from enum import Enum

from pydantic import BaseModel, Field

from sbcx.domain.sbc import SBCExtraction


class Source(str, Enum):
    parser = "parser"
    parser_llm = "parser+llm"  # parser and LLM agreed
    llm_fallback = "llm_fallback"  # LLM filled a gap or overrode a low-confidence parse
    default = "default"  # convention-based default


class DeductibleType(str, Enum):
    embedded = "embedded"
    aggregate = "aggregate"
    unknown = "unknown"


class FieldMeta(BaseModel):
    page: int | None = None
    raw_text: str | None = None
    source: Source = Source.parser
    confidence: float = Field(1.0, ge=0, le=1)
    reasons: list[str] = []
    rule_trace: list[str] = []


class Warning(BaseModel):
    code: str
    message: str
    path: str | None = None


class SectionSummary(BaseModel):
    section: str
    title: str
    summary: str
    highlights: list[str] = []
    source: str  # "llm" | "llm_retry" | "template"
    model: str | None = None
    prompt_version: str


class Versions(BaseModel):
    schema_version: str
    parser_version: str
    guideline_version: str
    fallback_model: str | None = None


class BenefitsExtras(BaseModel):
    deductible_type: DeductibleType = DeductibleType.unknown
    limitations: dict[str, str] = {}  # service_key -> limitations column text
    drug_limitations: str | None = None
    layout_source: str = "md"  # which layout view the services came from: md | pdf
    anchored_services: int = 0  # out of 26
    npages: int = 0


class BenefitsDocument(BaseModel):
    sha256: str
    versions: Versions
    benefits: SBCExtraction
    extras: BenefitsExtras
    provenance: dict[str, FieldMeta] = {}  # flat path (eval/score.py style) -> metadata
    warnings: list[Warning] = []
    doc_confidence: float = 1.0
    fallback_cells: int = 0
    summaries: list[SectionSummary] = []
