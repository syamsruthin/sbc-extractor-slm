"""Grounded plain-language summary per section: LLM -> one retry with the ungrounded numbers listed
-> deterministic template."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from sbcx.domain.benefits import BenefitsDocument, SectionSummary
from sbcx.domain.enrich.sections import SECTIONS, Section, section_input, template_summary
from sbcx.domain.explain.grounding import check, collect
from sbcx.infra.llm.base import LLMClient, LLMError
from sbcx.versions import SUMMARY_PROMPT_VERSION

SYSTEM = """You explain one section of a US health plan's benefits to someone who isn't an insurance expert.
Rules:
- Use only the facts in INPUT. Never add knowledge about typical plans.
- Every dollar amount, percentage and number you write must appear in INPUT.
- "deductible doesn't apply" means the member pays only the copay/coinsurance even before meeting the deductible.
- "after deductible" means the member pays the full allowed cost until the deductible is met.
- Mention important limits from the limitations text (visit limits, prior authorization needed) briefly.
- summary: 1-3 short sentences, at most 60 words. highlights: up to 3 phrases, at most 12 words each.
- Plain, neutral language. No advice ("you should"), no marketing words."""


class SummaryOut(BaseModel):
    summary: str = Field(max_length=600)
    highlights: list[str] = Field(max_length=5)


def _user(sec: Section, facts: dict) -> str:
    return f"SECTION: {sec.title}\nINPUT:\n{json.dumps(facts, ensure_ascii=False)}"


def summarize_section(
    doc: BenefitsDocument, sec: Section, llm: LLMClient | None, model: str
) -> SectionSummary:
    facts = section_input(doc, sec)
    allowed = collect(facts)
    if llm is not None:
        user = _user(sec, facts)
        for attempt in range(2):
            try:
                r = llm.complete_json(
                    task="section_summary",
                    system=SYSTEM,
                    user=user,
                    schema=SummaryOut,
                    model=model,
                    max_tokens=400,
                )
            except LLMError:
                break
            out = SummaryOut.model_validate(r.data)
            highlights = [h for h in out.highlights if h.strip()][:3]
            _, bad = check([out.summary, *highlights], allowed)
            if not bad:
                return SectionSummary(
                    section=sec.id,
                    title=sec.title,
                    summary=out.summary.strip(),
                    highlights=highlights,
                    source="llm" if attempt == 0 else "llm_retry",
                    model=r.model,
                    prompt_version=SUMMARY_PROMPT_VERSION,
                )
            user = (
                _user(sec, facts)
                + f"\n\nYour previous answer used numbers that are not in INPUT: {', '.join(bad)}. "
                "Rewrite it using only numbers from INPUT."
            )
    text, hl = template_summary(doc, sec)
    return SectionSummary(
        section=sec.id,
        title=sec.title,
        summary=text,
        highlights=hl,
        source="template",
        prompt_version=SUMMARY_PROMPT_VERSION,
    )


def summarize(
    doc: BenefitsDocument, llm: LLMClient | None, model: str, workers: int = 6
) -> list[SectionSummary]:
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(lambda s: summarize_section(doc, s, llm, model), SECTIONS))


def fake_summary(system: str, user: str) -> dict:
    """Fake mode: a short sentence that reuses only input wording, so it is grounded."""
    title = user.split("\n", 1)[0].removeprefix("SECTION: ")
    facts = json.loads(user.split("INPUT:\n", 1)[1].split("\n\nYour previous", 1)[0])
    first = ""
    if "services" in facts and facts["services"]:
        s = facts["services"][0]
        first = f" {s['service']}: {s['in_network']} in network."
    return {"summary": f"Summary of {title.lower()}.{first}", "highlights": []}
