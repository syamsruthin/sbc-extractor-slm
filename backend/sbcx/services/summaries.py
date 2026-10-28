"""Section summaries for a document: background job, stored inside the BenefitsDocument JSON."""

from __future__ import annotations

import logging

from sbcx.config import get_settings
from sbcx.domain.benefits import BenefitsDocument
from sbcx.domain.enrich.summarize import summarize
from sbcx.infra.db import session_scope
from sbcx.infra.llm import get_llm
from sbcx.infra.repos import DocumentRepo
from sbcx.logs import log
from sbcx.services.catalog import plan_hints

logger = logging.getLogger("sbcx.summaries")


def generate_summaries(doc_id: str) -> None:
    s = get_settings()
    with session_scope() as sess:
        row = DocumentRepo(sess).get(doc_id)
        if row is None or not row.benefits:
            return
        row.summaries_status = "running"
        doc = BenefitsDocument.model_validate(row.benefits)
        catalog_plan_id = row.catalog_plan_id
    try:
        hints = plan_hints(doc, catalog_plan_id)
        summaries = summarize(doc, get_llm(), s.model_summary, hints=hints)
    except Exception:
        logger.exception("summaries failed")
        with session_scope() as sess:
            row = DocumentRepo(sess).get(doc_id)
            if row:
                row.summaries_status = "failed"
        return
    with session_scope() as sess:
        row = DocumentRepo(sess).get(doc_id)
        if row is None or not row.benefits:
            return
        b = dict(row.benefits)
        b["summaries"] = [x.model_dump(mode="json") for x in summaries]
        row.benefits = b
        row.summaries_status = "ready"
    log(
        logger,
        "summaries",
        document_id=doc_id,
        sources={src: sum(x.source == src for x in summaries) for src in ("llm", "llm_retry", "template")},
    )
