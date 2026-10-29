import json

import httpx
import pytest
from pydantic import BaseModel

from sbcx.infra.llm.base import LLMError, strict_schema
from sbcx.infra.llm.cache import ResponseCache
from sbcx.infra.llm.fake import FakeLLMClient
from sbcx.infra.llm.openrouter import Budget, OpenRouterClient


class Out(BaseModel):
    summary: str
    n: int | None = None


def ok_body(content: dict, cost: float = 0.001) -> dict:
    return {
        "model": "m",
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": cost},
    }


def client(handler, tmp_path=None, cap=1.0, retries=2, calls=None):
    return OpenRouterClient(
        "k",
        Budget(cap),
        ResponseCache(tmp_path / "c.sqlite") if tmp_path else None,
        retries=retries,
        on_call=(calls.append if calls is not None else None),
        transport=httpx.MockTransport(handler),
    )


def call(c):
    return c.complete_json(task="t", system="s", user="u", schema=Out, model="m")


def test_success_logs_and_costs(monkeypatch):
    calls = []
    seen = {}

    def h(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json=ok_body({"summary": "x", "n": 1}))

    r = call(client(h, calls=calls))
    assert r.data == {"summary": "x", "n": 1} and r.cost_usd == 0.001
    assert seen["response_format"]["json_schema"]["strict"] is True
    assert seen["response_format"]["json_schema"]["schema"]["required"] == ["summary", "n"]
    assert calls[0]["outcome"] == "ok"


def test_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    seq = [httpx.Response(500), httpx.Response(200, json=ok_body({"summary": "y"}))]
    r = call(client(lambda req: seq.pop(0)))
    assert r.data["summary"] == "y"


def test_invalid_json_exhausts_retries(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    bad = {"model": "m", "choices": [{"message": {"content": "not json"}}], "usage": {}}
    with pytest.raises(LLMError):
        call(client(lambda req: httpx.Response(200, json=bad)))


def test_auth_error_not_retried():
    n = []

    def h(req):
        n.append(1)
        return httpx.Response(401)

    with pytest.raises(LLMError):
        call(client(h))
    assert len(n) == 1


def test_budget_stops_calls():
    c = client(lambda req: httpx.Response(200, json=ok_body({"summary": "x"}, cost=2.0)), cap=1.0)
    call(c)
    with pytest.raises(LLMError, match="budget"):
        call(c)


def test_cache_hit_skips_http(tmp_path):
    n = []

    def h(req):
        n.append(1)
        return httpx.Response(200, json=ok_body({"summary": "x"}))

    c = client(h, tmp_path)
    call(c)
    r = call(c)
    assert r.cached and len(n) == 1


def test_strict_schema_requires_all():
    s = strict_schema(Out.model_json_schema())
    assert s["additionalProperties"] is False and set(s["required"]) == {"summary", "n"}


def test_fake_script():
    f = FakeLLMClient({"t": [{"summary": "a"}, LLMError("x")]})
    assert call(f).data["summary"] == "a"
    with pytest.raises(LLMError):
        call(f)


def test_sensitive_calls_skip_the_cache_and_deny_data_collection(tmp_path):
    """v2.1 T3.4: personal text (usage descriptions) is never cached and only goes to providers that don't
    collect data."""
    bodies = []

    def h(req):
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json=ok_body({"summary": "x"}))

    c = client(h, tmp_path)
    for _ in range(2):
        r = c.complete_json(task="t", system="s", user="my health", schema=Out, model="m", sensitive=True)
        assert not r.cached
    assert len(bodies) == 2  # no cache hit
    assert bodies[0]["provider"] == {"require_parameters": True, "data_collection": "deny"}
    assert ResponseCache(tmp_path / "c.sqlite").get(ResponseCache.key(bodies[0])) is None
    call(c)
    assert "data_collection" not in bodies[-1]["provider"]  # other tasks unchanged (D9)
