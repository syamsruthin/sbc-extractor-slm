from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from sbcx.errors import AppError, install_error_handlers


def _app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    class Body(BaseModel):
        n: int

    @app.get("/boom")
    def boom():
        raise AppError("E_TEST", "bad thing", 418, {"x": 1})

    @app.get("/crash")
    def crash():
        raise RuntimeError("secret detail")

    @app.post("/v")
    def v(body: Body):
        return body

    return app


def test_unknown_route_uses_envelope(client):
    r = client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "E_NOT_FOUND"


def test_app_error():
    r = TestClient(_app()).get("/boom")
    assert r.status_code == 418
    assert r.json() == {"error": {"code": "E_TEST", "message": "bad thing", "details": {"x": 1}}}


def test_validation_error():
    r = TestClient(_app()).post("/v", json={"n": "x"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "E_VALIDATION"
    assert err["details"]["errors"][0]["loc"] == ["body", "n"]


def test_unhandled_error_hides_detail():
    r = TestClient(_app(), raise_server_exceptions=False).get("/crash")
    assert r.status_code == 500
    assert r.json()["error"] == {"code": "E_INTERNAL", "message": "Internal server error", "details": {}}
