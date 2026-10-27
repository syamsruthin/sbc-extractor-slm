"""get_llm(): the configured client, or None when LLM features are off/unconfigured."""

from __future__ import annotations

from functools import lru_cache

from sbcx.config import get_settings
from sbcx.infra.llm.base import LLMClient, LLMError, LLMResult

__all__ = ["LLMClient", "LLMError", "LLMResult", "get_llm", "reset_llm"]


@lru_cache
def get_llm() -> LLMClient | None:
    s = get_settings()
    if s.llm_mode == "fake":
        from sbcx.infra.llm.fake import FakeLLMClient
        from sbcx.infra.llm.fake_responders import default_responders

        return FakeLLMClient(default_responders())
    if s.llm_mode == "openrouter" and s.openrouter_api_key:
        from sbcx.infra.llm.cache import ResponseCache
        from sbcx.infra.llm.openrouter import Budget, OpenRouterClient

        def record(rec: dict) -> None:
            from sbcx.infra.repos import record_llm_call

            record_llm_call(rec)

        return OpenRouterClient(
            s.openrouter_api_key,
            Budget(s.llm_budget_usd),
            ResponseCache(s.var_dir / "llm_cache.sqlite"),
            timeout_s=s.llm_timeout_s,
            on_call=record,
        )
    return None


def reset_llm() -> None:
    get_llm.cache_clear()
