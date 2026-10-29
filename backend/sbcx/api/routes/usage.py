from fastapi import APIRouter

from sbcx.api.schemas import InterpretUsageRequest, InterpretUsageResponse
from sbcx.config import get_settings
from sbcx.errors import not_found
from sbcx.services import usage as svc

router = APIRouter(prefix="/usage", tags=["usage"])


@router.post(
    "/interpret",
    response_model=InterpretUsageResponse,
    summary="Turn a description of a year of care into usage events (not stored)",
)
def interpret_usage(req: InterpretUsageRequest):
    if not get_settings().intake_enabled:
        raise not_found("Feature", "usage intake")
    return svc.interpret(req)
