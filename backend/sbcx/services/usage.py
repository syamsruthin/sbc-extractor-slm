"""Natural-language usage intake (v2.1 M4). The description is sent to the LLM only here, marked sensitive
(never cached, data collection denied), and never stored or logged."""

from __future__ import annotations

import logging

from sbcx.api.schemas import InterpretedEvent, InterpretUsageRequest, InterpretUsageResponse, UnmodeledItem
from sbcx.config import get_settings
from sbcx.domain.compare.config import load_scenarios
from sbcx.domain.intake.prompt import build_system, build_user
from sbcx.domain.intake.schema import UsageDraft
from sbcx.domain.intake.validate import validate
from sbcx.errors import AppError
from sbcx.infra.llm import LLMError, get_llm
from sbcx.logs import log

logger = logging.getLogger("sbcx.intake")


def interpret(req: InterpretUsageRequest) -> InterpretUsageResponse:
    s = get_settings()
    llm = get_llm()
    if llm is None:
        raise AppError(
            "E_LLM_UNAVAILABLE", "Describing your year needs the AI service, which isn't configured.", 503
        )
    cfg = load_scenarios(str(s.config_dir))
    members = (req.members or ["you"]) if req.coverage_tier == "family" else ["you"]
    system = build_system(cfg.event_types, members)
    user = build_user(req.text)
    for attempt in range(2):
        try:
            r = llm.complete_json(
                task="usage_intake",
                system=system,
                user=user,
                schema=UsageDraft,
                model=s.model_intake,
                max_tokens=1200,
                sensitive=True,
            )
        except LLMError as e:
            raise AppError(
                "E_LLM_UNAVAILABLE", "The AI service didn't answer. Add events manually instead.", 503
            ) from e
        checked = validate(UsageDraft.model_validate(r.data), req.text, cfg.event_types, len(members))
        # counts only: the description and the model output never reach the logs
        log(
            logger,
            "usage_intake",
            attempt=attempt,
            events=len(checked.events),
            violations=len(checked.violations),
        )
        if not checked.violations:
            return InterpretUsageResponse(
                events=[
                    InterpretedEvent(
                        event=e.event, count=e.count, member=e.member, quote=e.quote, basis=e.basis
                    )
                    for e in checked.events
                ],
                unmodeled=[UnmodeledItem(quote=u.quote, reason=u.reason) for u in checked.unmodeled],
                model=r.model,
            )
        user = (
            build_user(req.text)
            + "\n\nYour previous answer broke the rules: "
            + "; ".join(checked.violations)
            + ". Fix those items or move them to unmodeled."
        )
    raise AppError(
        "E_INTAKE_INVALID", "We couldn't turn that description into events. Add them manually instead.", 422
    )


def fake_intake(system: str, user: str) -> dict:
    """SBCX_LLM_MODE=fake: picks a few phrases out of the description, so tests and E2E run without a model."""
    import re

    text = user.split("<description>\n", 1)[1].split("\n</description>", 1)[0]
    events, unmodeled = [], []
    for rx, event in (
        (r"(\d+) specialist visits?", "specialist_visit"),
        (r"(\d+) (?:physical therapy|pt) (?:visits|sessions)", "pt_visit"),
        (r"generic (?:prescription|drug|pill)s? (monthly|every month)", "generic_drug_fill"),
    ):
        if m := re.search(rf"(?i){rx}", text):
            n = 12 if m.group(1).lower() in ("monthly", "every month") else int(m.group(1))
            events.append({"event": event, "count": n, "member": 0, "quote": m.group(0), "basis": "stated"})
    if m := re.search(r"(?i)having a baby", text):
        events.append({"event": "childbirth", "count": 1, "member": 0, "quote": m.group(0), "basis": "once"})
    if m := re.search(r"(?i)dental cleanings?", text):
        unmodeled.append({"quote": m.group(0), "reason": "adult dental isn't covered by these plans"})
    return {"events": events, "unmodeled": unmodeled}
