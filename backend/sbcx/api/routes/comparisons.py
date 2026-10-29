from fastapi import APIRouter, BackgroundTasks, status

from sbcx.api.schemas import (
    ComparisonListItem,
    ComparisonResponse,
    ReferencePrices,
    ScenarioCatalog,
    UsageStats,
)
from sbcx.config import get_settings
from sbcx.domain.compare.config import load_prices, load_scenarios
from sbcx.domain.comparison import ComparisonRequest
from sbcx.infra.db import session_scope
from sbcx.infra.repos import llm_usage
from sbcx.services import comparison as svc

router = APIRouter(tags=["comparisons"])


def _explain_later(background: BackgroundTasks, cid: str) -> None:
    from sbcx.services.explanation import generate_explanation

    background.add_task(generate_explanation, cid)


@router.post(
    "/comparisons",
    response_model=ComparisonResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Compare 2-5 ready plans",
)
def create_comparison(req: ComparisonRequest, background: BackgroundTasks):
    resp = svc.create(req)
    if req.explain:
        _explain_later(background, resp.id)
    return resp


@router.get("/comparisons", response_model=list[ComparisonListItem], summary="Recent comparisons")
def list_comparisons():
    return svc.recent()


@router.delete(
    "/comparisons", status_code=status.HTTP_204_NO_CONTENT, summary="Delete every saved comparison"
)
def delete_comparisons():
    svc.delete_all()


@router.get(
    "/comparisons/{cid}", response_model=ComparisonResponse, summary="A comparison with its explanation"
)
def get_comparison(cid: str):
    return svc.get(cid)


@router.delete(
    "/comparisons/{cid}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a saved comparison"
)
def delete_comparison(cid: str):
    svc.delete(cid)


@router.post(
    "/comparisons/{cid}/explanation",
    response_model=ComparisonResponse,
    status_code=202,
    summary="Generate (or regenerate) the explanation",
)
def regenerate_explanation(cid: str, background: BackgroundTasks):
    resp = svc.get(cid)
    if resp.explanation_status != "running":
        svc.set_explanation(cid, "pending")
        _explain_later(background, cid)
    return svc.get(cid)


@router.get(
    "/meta/scenarios", response_model=ScenarioCatalog, tags=["meta"], summary="Usage presets and event types"
)
def scenarios():
    cfg = load_scenarios(str(get_settings().config_dir))
    return ScenarioCatalog(presets=cfg.presets, event_types=cfg.event_types)


@router.get(
    "/meta/reference-prices",
    response_model=ReferencePrices,
    tags=["meta"],
    summary="Reference allowed amounts",
)
def reference_prices():
    p = load_prices(str(get_settings().config_dir))
    return ReferencePrices(version=p.version, source=p.source, prices=p.flat(), labels=p.labels())


@router.get("/meta/usage", response_model=UsageStats, tags=["meta"], summary="LLM calls and spend")
def usage():
    with session_scope() as s:
        return UsageStats(llm=llm_usage(s))
