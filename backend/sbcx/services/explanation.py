"""Background job: explanation for a stored comparison."""

from __future__ import annotations

import logging

from sbcx.config import get_settings
from sbcx.domain.benefits import BenefitsDocument
from sbcx.domain.explain.generate import explain
from sbcx.infra.db import session_scope
from sbcx.infra.llm import get_llm
from sbcx.infra.repos import DocumentRepo
from sbcx.logs import log
from sbcx.services import comparison as cmp

logger = logging.getLogger("sbcx.explanation")
KEEP_SECTIONS = ("deductible_oop", "office_visits", "drugs", "hospital", "pregnancy")


def _summaries(resp) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    with session_scope() as s:
        for p in resp.result.plans:
            row = DocumentRepo(s).get(p.document_id)
            if not row or not row.benefits:
                continue
            doc = BenefitsDocument.model_validate(row.benefits)
            got = {
                x.section: x.summary
                for x in doc.summaries
                if x.section in KEEP_SECTIONS and x.source != "template"
            }
            if got:
                out[p.plan_key] = got
    return out


def generate_explanation(cid: str) -> None:
    s = get_settings()
    cmp.set_explanation(cid, "running")
    try:
        resp = cmp.get(cid)
        rec = explain(resp.result, get_llm(), s.model_explanation, _summaries(resp))
    except Exception:
        logger.exception("explanation failed")
        cmp.set_explanation(cid, "failed")
        return
    cmp.set_explanation(cid, "ready", rec)
    log(
        logger,
        "explanation",
        comparison_id=cid,
        source=rec.source,
        grounded=rec.grounding.ok,
        violations=len(rec.grounding.violations),
    )
