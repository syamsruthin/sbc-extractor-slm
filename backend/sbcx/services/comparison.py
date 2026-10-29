"""Create and read comparisons. The result is computed synchronously (pure CPU, ~100 ms); the
explanation is generated in the background."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sbcx.api.schemas import ComparisonListItem, ComparisonResponse
from sbcx.config import get_settings
from sbcx.domain.compare.config import load_prices, load_scenarios
from sbcx.domain.compare.engine import PlanInput, compare
from sbcx.domain.comparison import ComparisonRequest, ComparisonResult
from sbcx.domain.explanation import ExplanationRecord
from sbcx.errors import AppError, not_found
from sbcx.infra.db import session_scope
from sbcx.infra.models import ComparisonRow
from sbcx.infra.repos import CatalogRepo, ComparisonRepo
from sbcx.services.documents import get as get_doc
from sbcx.services.documents import require_ready
from sbcx.versions import ENGINE_VERSION


def _plan_inputs(req: ComparisonRequest) -> list[PlanInput]:
    out = []
    for did in req.document_ids:
        doc = require_ready(did)
        row = get_doc(did)
        cat = None
        if row.catalog_plan_id:
            with session_scope() as s:
                c = CatalogRepo(s).get(row.catalog_plan_id)
                cat = (c.plan_id, c.metal, c.coverage_examples, c.hsa_eligible) if c else None
        out.append(
            PlanInput(
                document_id=did,
                doc=doc,
                catalog_plan_id=cat[0] if cat else None,
                metal=cat[1] if cat else None,
                coverage_examples=cat[2] if cat else None,
                hsa_eligible=cat[3] if cat else None,
            )
        )
    return out


def run(req: ComparisonRequest) -> ComparisonResult:
    s = get_settings()
    cfg = load_scenarios(str(s.config_dir))
    unknown = [i for i in req.scenario_ids if cfg.preset(i) is None]
    if unknown:
        raise AppError(
            "E_UNKNOWN_SCENARIO",
            f"Unknown scenario: {', '.join(unknown)}",
            422,
            {"known": [p.id for p in cfg.presets]},
        )
    if req.custom_scenario:
        bad = [e.event for e in req.custom_scenario.events if e.event not in cfg.event_types]
        if bad:
            raise AppError("E_UNKNOWN_EVENT", f"Unknown event type: {', '.join(bad)}", 422)
    return compare(_plan_inputs(req), req, cfg, load_prices(str(s.config_dir)))


def create(req: ComparisonRequest) -> ComparisonResponse:
    result = run(req)
    status = "pending" if req.explain else "skipped"
    with session_scope() as s:
        row = ComparisonRepo(s).add(
            ComparisonRow(
                request=req.model_dump(mode="json"),
                result=result.model_dump(mode="json"),
                engine_version=ENGINE_VERSION,
                explanation_status=status,
            )
        )
        return to_response(row)


def to_response(row: ComparisonRow) -> ComparisonResponse:
    return ComparisonResponse(
        id=row.id,
        created_at=row.created_at,
        request=ComparisonRequest.model_validate(row.request),
        result=ComparisonResult.model_validate(row.result),
        explanation_status=row.explanation_status,  # type: ignore[arg-type]
        explanation=ExplanationRecord.model_validate(row.explanation) if row.explanation else None,
    )


def get(cid: str) -> ComparisonResponse:
    with session_scope() as s:
        row = ComparisonRepo(s).get(cid)
        if row is None:
            raise not_found("Comparison", cid)
        return to_response(row)


def recent() -> list[ComparisonListItem]:
    with session_scope() as s:
        return [
            ComparisonListItem(
                id=r.id,
                created_at=r.created_at,
                plan_names=[p.get("plan_name") or "Plan" for p in r.result.get("plans", [])],
                scenario_labels=[s["scenario"]["label"] for s in r.result.get("scenarios", [])],
            )
            for r in ComparisonRepo(s).recent()
        ]


def delete(cid: str) -> None:
    with session_scope() as s:
        if not ComparisonRepo(s).delete(cid):
            raise not_found("Comparison", cid)


def delete_all() -> int:
    with session_scope() as s:
        return ComparisonRepo(s).delete_all()


def purge_older_than(days: int) -> int:
    """Delete comparisons older than `days` (retention, SBCX_COMPARISON_RETENTION_DAYS)."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with session_scope() as s:
        return ComparisonRepo(s).delete_older_than(cutoff)


def set_explanation(cid: str, status: str, record: ExplanationRecord | None = None) -> None:
    with session_scope() as s:
        row = ComparisonRepo(s).get(cid)
        if row is None:
            return
        row.explanation_status = status
        if record is not None:
            row.explanation = record.model_dump(mode="json")
