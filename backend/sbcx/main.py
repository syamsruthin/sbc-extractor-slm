"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sbcx.api.routes import catalog, comparisons, documents, health, usage
from sbcx.config import get_settings
from sbcx.errors import install_error_handlers
from sbcx.infra.db import init_db
from sbcx.logs import RequestIdMiddleware, setup_logging
from sbcx.versions import APP_VERSION

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    days = get_settings().comparison_retention_days
    if days:
        from sbcx.services.comparison import purge_older_than

        n = purge_older_than(days)
        logging.getLogger("sbcx").info("purged %d comparisons older than %d days", n, days)
    logging.getLogger("sbcx").info("startup complete")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(
        title="SBC Plan Comparison API",
        version=APP_VERSION,
        description="Extract standardized benefits from SBC PDFs, compare plans, explain the differences.",
        lifespan=lifespan,
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id"],
    )
    install_error_handlers(app)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health.router)
    api.include_router(documents.router)
    api.include_router(catalog.router)
    api.include_router(comparisons.router)
    api.include_router(usage.router)
    app.include_router(api)
    return app


app = create_app()
