"""Default fake answers per task (SBCX_LLM_MODE=fake), provided by the modules that own each task."""

from __future__ import annotations

import importlib
from typing import Any

RESPONDERS = {
    "cell_fallback": "sbcx.domain.extract.fallback:fake_fallback",
    "section_summary": "sbcx.domain.enrich.summarize:fake_summary",
    "explanation": "sbcx.domain.explain.generate:fake_explanation",
    "usage_intake": "sbcx.services.usage:fake_intake",
}


def default_responders() -> dict[str, Any]:
    out = {}
    for task, ref in RESPONDERS.items():
        mod, fn = ref.split(":")
        try:
            out[task] = getattr(importlib.import_module(mod), fn)
        except (ImportError, AttributeError):
            continue
    return out
