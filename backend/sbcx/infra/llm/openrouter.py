"""OpenRouter client: strict JSON-schema outputs, retries, timeout, spend cap, response cache and a
call log. Pattern from src/label_sbcs.py."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from sbcx.infra.llm.base import LLMError, LLMResult, strict_schema
from sbcx.infra.llm.cache import ResponseCache
from sbcx.logs import log

API_URL = "https://openrouter.ai/api/v1/chat/completions"
logger = logging.getLogger("sbcx.llm")


class Budget:
    """Process-wide spend tracker; new calls stop once the cap is reached."""

    def __init__(self, cap_usd: float):
        self.cap, self.spent = cap_usd, 0.0
        self._lock = threading.Lock()

    def add(self, cost: float) -> None:
        with self._lock:
            self.spent += cost

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.cap


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        budget: Budget,
        cache: ResponseCache | None = None,
        timeout_s: float = 90.0,
        retries: int = 2,
        on_call: Callable[[dict[str, Any]], None] | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key
        self.budget = budget
        self.cache = cache
        self.retries = retries
        self.on_call = on_call
        self._http = httpx.Client(timeout=timeout_s, transport=transport)

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
        sensitive: bool = False,
    ) -> LLMResult:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": task,
                "strict": True,
                "schema": strict_schema(schema.model_json_schema()),
            },
        }
        provider: dict[str, Any] = {"require_parameters": True}  # only providers that enforce the schema
        if sensitive:
            provider["data_collection"] = "deny"  # only providers that don't store or train on prompts
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": response_format,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "reasoning": {"enabled": False},  # thinking tokens are billed as output
            "provider": provider,
            "usage": {"include": True},
        }
        cache = None if sensitive else self.cache  # personal text never lands in the response cache
        key = ResponseCache.key(payload)
        if cache and (hit := cache.get(key)) is not None:
            return LLMResult(data=hit["data"], model=hit.get("model", model), cached=True)
        if self.budget.exhausted:
            raise LLMError(f"LLM budget of ${self.budget.cap:.2f} exhausted")

        last: Exception | None = None
        for attempt in range(self.retries + 1):
            t0 = time.perf_counter()
            try:
                resp = self._http.post(
                    API_URL, headers={"Authorization": f"Bearer {self.api_key}"}, json=payload
                )
                if resp.status_code in (401, 402, 403):
                    raise LLMError(f"OpenRouter refused the request (HTTP {resp.status_code})")
                if resp.status_code >= 500 or resp.status_code == 429:
                    raise httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
                resp.raise_for_status()
                body = resp.json()
                if "error" in body:
                    raise LLMError(f"OpenRouter error: {body['error']}")
                content = body["choices"][0]["message"]["content"]
                usage = body.get("usage") or {}
                cost = float(usage.get("cost") or 0.0)
                self.budget.add(cost)
                data = schema.model_validate(json.loads(content)).model_dump(mode="json")
                result = LLMResult(
                    data=data,
                    model=body.get("model", model),
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    cost_usd=cost,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
                if cache:
                    cache.put(key, {"data": data, "model": result.model})
                self._log(task, result, "ok")
                return result
            except LLMError as e:
                self._log(task, None, f"error: {e}", model)
                raise
            except (httpx.HTTPError, ValueError, ValidationError, KeyError) as e:
                last = e
                if attempt < self.retries:
                    time.sleep(min(8.0, 1.5 * 2**attempt))
        self._log(task, None, f"failed: {type(last).__name__}", model)
        raise LLMError(f"LLM call failed after {self.retries + 1} attempts: {type(last).__name__}: {last}")

    def _log(self, task: str, r: LLMResult | None, outcome: str, model: str | None = None) -> None:
        rec: dict[str, Any] = {
            "task": task,
            "model": r.model if r else model,
            "prompt_tokens": r.prompt_tokens if r else 0,
            "completion_tokens": r.completion_tokens if r else 0,
            "cost_usd": r.cost_usd if r else 0.0,
            "latency_ms": r.latency_ms if r else 0,
            "outcome": outcome,
        }
        log(logger, "llm_call", **rec)
        if self.on_call:
            try:
                self.on_call(rec)
            except Exception:
                logger.exception("call log failed")
