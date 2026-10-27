"""Database tables. JSON columns hold the versioned Pydantic contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from sbcx.infra.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(16), default="upload")  # upload | catalog
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    npages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plan_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    doc_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    summaries_status: Mapped[str] = mapped_column(
        String(16), default="pending"
    )  # pending|running|ready|skipped|failed
    benefits: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # BenefitsDocument
    catalog_plan_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class CatalogPlanRow(Base):
    __tablename__ = "catalog_plans"

    plan_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # HIOS plan id + variant
    plan_year: Mapped[int] = mapped_column(Integer, default=2026)
    state: Mapped[str] = mapped_column(String(2), index=True)
    issuer: Mapped[str] = mapped_column(String(255), index=True)
    plan_name: Mapped[str] = mapped_column(String(255))
    metal: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    plan_type: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    sbc_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    deductible_individual: Mapped[float | None] = mapped_column(Float, nullable=True)
    oop_individual: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage_examples: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # from the Plan Attributes PUF
    status: Mapped[str] = mapped_column(String(32), default="pending")


class PremiumRow(Base):
    __tablename__ = "premiums"
    __table_args__ = (Index("ix_premium_lookup", "plan_key", "rating_area", "age"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_key: Mapped[str] = mapped_column(String(16), index=True)  # 14-char HIOS standard component id
    state: Mapped[str] = mapped_column(String(2))
    rating_area: Mapped[str] = mapped_column(String(32))
    age: Mapped[str] = mapped_column(String(16))  # "0-14", "21", ..., "64 and over"
    monthly_premium: Mapped[float] = mapped_column(Float)


class ComparisonRow(Base):
    __tablename__ = "comparisons"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    request: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    engine_version: Mapped[str] = mapped_column(String(16))
    explanation_status: Mapped[str] = mapped_column(
        String(16), default="pending"
    )  # pending|running|ready|failed|skipped
    explanation: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ExplanationRecord
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LLMCallRow(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
