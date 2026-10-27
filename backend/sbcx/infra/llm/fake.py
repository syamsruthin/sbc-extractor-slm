"""Deterministic stand-in for tests and E2E (SBCX_LLM_MODE=fake). A responder per task builds the
answer from the prompt, so fake output is still grounded in the input."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from sbcx.infra.llm.base import LLMError, LLMResult

Responder = Callable[[str, str], dict[str, Any]]  # (system, user) -> data


class FakeLLMClient:
    def __init__(self, responders: dict[str, Responder | list[dict | Exception]] | None = None):
        self.responders: dict[str, Any] = responders or {}
        self.calls: list[dict[str, Any]] = []

    def complete_json(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: type[BaseModel],
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 2000,
    ) -> LLMResult:
        self.calls.append({"task": task, "system": system, "user": user, "model": model})
        r = self.responders.get(task)
        if r is None:
            raise LLMError(f"fake LLM has no responder for task {task!r}")
        if isinstance(r, list):  # scripted sequence
            if not r:
                raise LLMError("fake LLM script exhausted")
            item = r.pop(0)
            if isinstance(item, Exception):
                raise item
            data = item
        else:
            data = r(system, user)
        return LLMResult(data=schema.model_validate(data).model_dump(mode="json"), model=f"fake/{model}")
