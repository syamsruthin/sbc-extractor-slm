from typing import Literal

from fastapi import APIRouter, Query

from sbcx.api.schemas import (
    CatalogFacets,
    CatalogPage,
    CatalogPlan,
    HouseholdQuote,
    PremiumQuotes,
    RatingAreas,
)
from sbcx.errors import AppError
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


@router.get("/rating-areas", response_model=RatingAreas, summary="Rating areas with premiums in a state")
def get_rating_areas(state: str = Query(..., min_length=2, max_length=2)):
    return svc.rating_areas(state)


@router.get("/plans/{plan_id}", response_model=CatalogPlan, summary="One catalog plan")
def get_plan(plan_id: str):
    return svc.get_plan(plan_id)


@router.get(
    "/plans/{plan_id}/premiums", response_model=PremiumQuotes, summary="Monthly premiums by rating area"
)
def get_premiums(plan_id: str, age: str = Query("40", max_length=12), rating_area: str | None = None):
    return svc.premiums(plan_id, age, rating_area)


@router.get(
    "/plans/{plan_id}/premium-quote",
    response_model=HouseholdQuote,
    summary="Monthly premium for a household (ages) in one rating area",
)
def get_premium_quote(
    plan_id: str,
    rating_area: str = Query(..., min_length=1, max_length=32),
    ages: str = Query(..., max_length=60, description="Comma-separated ages, 1-10 members, 0-120"),
):
    try:
        parsed = [int(a) for a in ages.split(",") if a.strip()]
    except ValueError:
        parsed = []
    if not 1 <= len(parsed) <= 10 or any(a < 0 or a > 120 for a in parsed):
        raise AppError("E_VALIDATION", "ages must be 1-10 comma-separated whole numbers from 0 to 120", 422)
    return svc.household_quote(plan_id, rating_area, parsed)
