"""Repositories: the only place that knows table layouts. Services pass sessions in."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from sbcx.infra.db import session_scope
from sbcx.infra.models import CatalogPlanRow, ComparisonRow, DocumentRow, LLMCallRow, PremiumRow


class DocumentRepo:
    def __init__(self, s: Session):
        self.s = s

    def get(self, doc_id: str) -> DocumentRow | None:
        return self.s.get(DocumentRow, doc_id)

    def by_sha(self, sha256: str) -> DocumentRow | None:
        return self.s.scalar(select(DocumentRow).where(DocumentRow.sha256 == sha256))

    def add(self, row: DocumentRow) -> DocumentRow:
        self.s.add(row)
        self.s.flush()
        return row

    def list_uploads(self, limit: int = 100) -> Sequence[DocumentRow]:
        q = select(DocumentRow).where(DocumentRow.source == "upload").order_by(DocumentRow.created_at.desc())
        return self.s.scalars(q.limit(limit)).all()

    def delete(self, row: DocumentRow) -> None:
        self.s.delete(row)


class CatalogRepo:
    def __init__(self, s: Session):
        self.s = s

    def get(self, plan_id: str) -> CatalogPlanRow | None:
        return self.s.get(CatalogPlanRow, plan_id)

    def upsert(self, **fields: Any) -> CatalogPlanRow:
        row = self.get(fields["plan_id"])
        if row is None:
            row = CatalogPlanRow(**fields)
            self.s.add(row)
        else:
            for k, v in fields.items():
                setattr(row, k, v)
        return row

    def search(
        self,
        *,
        state: str | None = None,
        metal: str | None = None,
        plan_type: str | None = None,
        issuer: str | None = None,
        q: str | None = None,
        ready_only: bool = True,
        offset: int = 0,
        limit: int = 25,
        sort: str = "plan_name",
    ) -> tuple[int, Sequence[CatalogPlanRow]]:
        conds = []
        if ready_only:
            conds.append(CatalogPlanRow.status == "ready")
        if state:
            conds.append(CatalogPlanRow.state == state.upper())
        if metal:
            conds.append(func.lower(CatalogPlanRow.metal) == metal.lower())
        if plan_type:
            conds.append(CatalogPlanRow.plan_type == plan_type.upper())
        if issuer:
            conds.append(CatalogPlanRow.issuer == issuer)
        if q:
            like = f"%{q.lower()}%"
            conds.append(
                or_(
                    func.lower(CatalogPlanRow.plan_name).like(like),
                    func.lower(CatalogPlanRow.issuer).like(like),
                    func.lower(CatalogPlanRow.plan_id).like(like),
                )
            )
        base = select(CatalogPlanRow).where(*conds)
        total = self.s.scalar(select(func.count()).select_from(base.subquery())) or 0
        order = {
            "plan_name": CatalogPlanRow.plan_name,
            "deductible": CatalogPlanRow.deductible_individual,
            "oop": CatalogPlanRow.oop_individual,
        }.get(sort, CatalogPlanRow.plan_name)
        rows = self.s.scalars(
            base.order_by(order.is_(None), order, CatalogPlanRow.plan_id).offset(offset).limit(limit)
        ).all()
        return total, rows

    def facets(self) -> dict[str, list[tuple[Any, int]]]:
        out = {}
        for name, col in (
            ("state", CatalogPlanRow.state),
            ("metal", CatalogPlanRow.metal),
            ("plan_type", CatalogPlanRow.plan_type),
            ("issuer", CatalogPlanRow.issuer),
        ):
            rows = self.s.execute(
                select(col, func.count())
                .where(CatalogPlanRow.status == "ready", col.is_not(None))
                .group_by(col)
                .order_by(col)
            ).all()
            out[name] = [(r[0], r[1]) for r in rows]
        return out


class PremiumRepo:
    def __init__(self, s: Session):
        self.s = s

    def lookup(self, plan_key: str, age: str, rating_area: str | None = None) -> Sequence[PremiumRow]:
        q = select(PremiumRow).where(PremiumRow.plan_key == plan_key, PremiumRow.age == age)
        if rating_area:
            q = q.where(PremiumRow.rating_area == rating_area)
        return self.s.scalars(q.order_by(PremiumRow.rating_area)).all()

    def count(self) -> int:
        return self.s.scalar(select(func.count()).select_from(PremiumRow)) or 0

    def rating_areas(self, state: str) -> list[tuple[str, int]]:
        """(rating area, number of plans priced there) for one state."""
        rows = self.s.execute(
            select(PremiumRow.rating_area, func.count(func.distinct(PremiumRow.plan_key)))
            .where(PremiumRow.state == state)
            .group_by(PremiumRow.rating_area)
        ).all()
        return [(a, int(n)) for a, n in rows]

    def rates(self, plan_key: str, rating_area: str, bands: list[str]) -> dict[str, float]:
        rows = self.s.scalars(
            select(PremiumRow).where(
                PremiumRow.plan_key == plan_key,
                PremiumRow.rating_area == rating_area,
                PremiumRow.age.in_(bands),
            )
        ).all()
        return {r.age: r.monthly_premium for r in rows}


class ComparisonRepo:
    def __init__(self, s: Session):
        self.s = s

    def get(self, cid: str) -> ComparisonRow | None:
        return self.s.get(ComparisonRow, cid)

    def add(self, row: ComparisonRow) -> ComparisonRow:
        self.s.add(row)
        self.s.flush()
        return row

    def recent(self, limit: int = 20) -> Sequence[ComparisonRow]:
        return self.s.scalars(
            select(ComparisonRow).order_by(ComparisonRow.created_at.desc()).limit(limit)
        ).all()

    def delete(self, cid: str) -> bool:
        row = self.s.get(ComparisonRow, cid)
        if row is None:
            return False
        self.s.delete(row)
        return True

    def delete_all(self) -> int:
        return self.s.execute(delete(ComparisonRow)).rowcount or 0  # type: ignore[attr-defined]

    def delete_older_than(self, cutoff: datetime) -> int:
        return (
            self.s.execute(delete(ComparisonRow).where(ComparisonRow.created_at < cutoff)).rowcount  # type: ignore[attr-defined]
            or 0
        )


def record_llm_call(rec: dict[str, Any]) -> None:
    with session_scope() as s:
        s.add(
            LLMCallRow(
                **{
                    k: rec[k]
                    for k in ("task", "model", "prompt_tokens", "completion_tokens", "cost_usd", "latency_ms")
                },
                outcome=str(rec["outcome"])[:255],
            )
        )


def llm_usage(s: Session) -> dict[str, Any]:
    rows = s.execute(
        select(LLMCallRow.task, func.count(), func.sum(LLMCallRow.cost_usd)).group_by(LLMCallRow.task)
    ).all()
    return {r[0]: {"calls": r[1], "cost_usd": round(r[2] or 0.0, 5)} for r in rows}
