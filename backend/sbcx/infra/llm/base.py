"""LLM client protocol. Every LLM step asks for JSON matching a Pydantic model; callers always
have a non-LLM path for LLMError."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel


class LLMError(Exception):
    """Any failure the caller should treat as 'no LLM answer' (transport, budget, invalid output)."""


@dataclass
class LLMResult:
    data: dict[str, Any]
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    cached: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class LLMClient(Protocol):
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
    ) -> LLMResult: ...


def strict_schema(schema: Any) -> Any:
    """Disallow extra keys and require every property, as strict structured outputs need
    (same idea as src/label_sbcs.py)."""
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            schema["additionalProperties"] = False
            if "properties" in schema:
                schema["required"] = list(schema["properties"])
        schema.pop("default", None)
        for v in schema.values():
            strict_schema(v)
    elif isinstance(schema, list):
        for item in schema:
            strict_schema(item)
    return schema
