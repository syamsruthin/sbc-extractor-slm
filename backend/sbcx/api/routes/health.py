from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from sbcx.config import get_settings
from sbcx.versions import APP_VERSION, ENGINE_VERSION, PARSER_VERSION

router = APIRouter(tags=["meta"])


class Health(BaseModel):
    status: str
    version: str
    parser_version: str
    engine_version: str
    llm_mode: str
    llm_configured: bool
    db: bool


@router.get("/health", response_model=Health)
def health() -> Health:
    s = get_settings()
    db_ok = True
    try:
        from sbcx.infra.db import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
    except Exception:
        db_ok = False
    return Health(
        status="ok" if db_ok else "degraded",
        version=APP_VERSION,
        parser_version=PARSER_VERSION,
        engine_version=ENGINE_VERSION,
        llm_mode=s.llm_mode,
        llm_configured=s.llm_available,
        db=db_ok,
    )
