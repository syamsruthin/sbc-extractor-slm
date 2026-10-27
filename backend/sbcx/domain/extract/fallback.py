"""Cell-level LLM fallback (LLD §3.9). Only cells whose confidence is below the threshold are sent,
each with its own source text. A result is accepted only when every number in it appears in that
text, so the LLM can't invent prices."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

from sbcx.domain.benefits import BenefitsDocument, Source, Warning
from sbcx.domain.sbc import CostShare, normalize
from sbcx.infra.llm.base import LLMClient, LLMError

SYSTEM = """You read one cell of a US health plan Summary of Benefits and Coverage (SBC) cost-sharing table
and return what the member pays, as JSON. Rules:
- Use only the cell text given. Never infer from typical plans.
- Money is a number in dollars (1500, not "$1,500"); percentages are 0-100.
- "No charge" / "$0 copay" -> covered=true, copay=0, coinsurance_pct=0.
- "0% coinsurance" -> coinsurance_pct=0, copay=null.
- "Not covered" -> covered=false, every other field null.
- "deductible does not apply" / "waived" -> deductible_applies=false; "after deductible" / "subject to
  deductible" -> true; nothing said in this cell -> null.
- Fill BOTH copay and coinsurance_pct only for one combined charge ("$250 copay then 20% coinsurance").
- Different prices for different parts -> the FIRST listed part goes in the fields, other parts in note.
- "First N visits $X, then $Y" or "Visit 1: $X; Visit 2 and after: $Y" -> use the LATER charge; the
  first-visits charge goes in note.
- note: at most 150 characters, only terms the fields can't express; otherwise null.
Return one result per input cell, with the same id."""


class CellOut(BaseModel):
    id: str
    covered: bool
    copay: float | None
    coinsurance_pct: float | None
    deductible_applies: bool | None
    note: str | None


class FallbackOut(BaseModel):
    cells: list[CellOut]


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[float]:
    return {float(x.replace(",", "")) for x in _NUM.findall(text or "")}


def grounded(cell: CellOut, text: str) -> bool:
    nums = numbers_in(text)
    zero_ok = bool(re.search(r"(?i)no charge|no cost|\$0\b|0%|covered (at|in full at) 100%|no copay", text))
    for v in (cell.copay, cell.coinsurance_pct):
        if v is None:
            continue
        if v == 0 and zero_ok:
            continue
        if v not in nums:
            return False
    return True


def _same(a: dict | None, b: dict) -> bool:
    if a is None:
        return False
    return all(a.get(k) == b.get(k) for k in ("covered", "copay", "coinsurance_pct", "deductible_applies"))


def select_cells(doc: BenefitsDocument, threshold: float) -> list[dict[str, Any]]:
    out = []
    for key, svc in doc.benefits.services:
        for net in ("in_network", "out_of_network"):
            meta = doc.provenance.get(f"services.{key}.{net}.copay")
            if not meta or not meta.raw_text or meta.confidence >= threshold:
                continue
            cell = getattr(svc, net)
            out.append(
                {
                    "id": f"services.{key}.{net}",
                    "service": key.replace("_", " "),
                    "network": net.replace("_", "-"),
                    "text": meta.raw_text,
                    "limitations": doc.extras.limitations.get(key, "")[:300],
                    "parser_guess": cell.model_dump() if cell else None,
                    "reasons": meta.reasons,
                }
            )
    return out


def resolve(
    doc: BenefitsDocument, llm: LLMClient | None, model: str, threshold: float, batch: int = 8
) -> int:
    """Mutates doc in place. Returns the number of cells sent to the LLM."""
    cells = select_cells(doc, threshold)
    if not cells or llm is None:
        return 0
    sent = 0
    for i in range(0, len(cells), batch):
        chunk = cells[i : i + batch]
        user = "CELLS:\n" + json.dumps(
            [
                {k: c[k] for k in ("id", "service", "network", "text", "limitations", "parser_guess")}
                for c in chunk
            ],
            ensure_ascii=False,
        )
        try:
            res = llm.complete_json(
                task="cell_fallback", system=SYSTEM, user=user, schema=FallbackOut, model=model
            )
        except LLMError:
            for c in chunk:
                _flag(doc, c["id"], "needs_review")
            continue
        sent += len(chunk)
        doc.versions.fallback_model = res.model
        by_id = {c.id: c for c in FallbackOut.model_validate(res.data).cells}
        for c in chunk:
            out = by_id.get(c["id"])
            if out is None or not grounded(out, c["text"]):
                _flag(doc, c["id"], "needs_review")
                continue
            new = out.model_dump(exclude={"id"})
            if new["note"] and len(new["note"]) > 150:
                new["note"] = new["note"][:147].rsplit(" ", 1)[0] + "..."
            _, key, net = c["id"].split(".")
            if _same(c["parser_guess"], new):
                _set_meta(doc, c["id"], Source.parser_llm, max(0.95, _conf(doc, c["id"])))
            else:
                setattr(getattr(doc.benefits.services, key), net, CostShare(**new))
                _set_meta(doc, c["id"], Source.llm_fallback, 0.75)
                doc.warnings.append(
                    Warning(
                        code="W_FALLBACK_OVERRIDE",
                        path=c["id"],
                        message=f"{c['service'].capitalize()} ({c['network']}) was re-read by the LLM.",
                    )
                )
    normalize(doc.benefits)
    doc.fallback_cells = sent
    return sent


def _conf(doc: BenefitsDocument, prefix: str) -> float:
    return doc.provenance[f"{prefix}.copay"].confidence


def _set_meta(doc: BenefitsDocument, prefix: str, source: Source, conf: float) -> None:
    for p, m in doc.provenance.items():
        if p.startswith(prefix + "."):
            m.source, m.confidence = source, round(conf, 3)


def _flag(doc: BenefitsDocument, prefix: str, reason: str) -> None:
    for p, m in doc.provenance.items():
        if p.startswith(prefix + ".") and reason not in m.reasons:
            m.reasons.append(reason)


def fake_fallback(system: str, user: str) -> dict:
    """Fake mode: agree with the parser (grounded by construction)."""
    cells = json.loads(user.split("CELLS:\n", 1)[1])
    out = []
    for c in cells:
        g = c["parser_guess"] or {
            "covered": True,
            "copay": None,
            "coinsurance_pct": None,
            "deductible_applies": None,
            "note": None,
        }
        out.append(
            {
                "id": c["id"],
                **{
                    k: g.get(k) for k in ("covered", "copay", "coinsurance_pct", "deductible_applies", "note")
                },
            }
        )
    return {"cells": out}
