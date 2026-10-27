from typing import Literal

from fastapi import APIRouter, Query

from sbcx.api.schemas import CatalogFacets, CatalogPage, CatalogPlan, PremiumQuotes
from sbcx.services import catalog as svc

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/plans", response_model=CatalogPage, summary="Search marketplace plans")
def search_plans(
    state: str | None = Query(None, min_length=2, max_length=2),
    metal: str | None = None,
    plan_type: str | None = None,
    issuer: str | None = None,
    q: str | None = Query(None, max_length=100),
    sort: Literal["plan_name", "deductible", "oop"] = "plan_name",
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    return svc.search(
        state=state,
        metal=metal,
        plan_type=plan_type,
        issuer=issuer,
        q=q,
        sort=sort,
        offset=offset,
        limit=limit,
    )


@router.get("/facets", response_model=CatalogFacets, summary="Filter values with counts")
def get_facets():
    return svc.facets()


@router.get("/plans/{plan_id}", response_model=CatalogPlan, summary="One catalog plan")
def get_plan(plan_id: str):
    return svc.get_plan(plan_id)


@router.get(
    "/plans/{plan_id}/premiums", response_model=PremiumQuotes, summary="Monthly premiums by rating area"
)
def get_premiums(plan_id: str, age: str = Query("40", max_length=12), rating_area: str | None = None):
    return svc.premiums(plan_id, age, rating_area)
