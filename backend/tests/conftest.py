import os
import tempfile
from pathlib import Path

import pytest

# Isolate every test run: temp var dir + sqlite, fake LLM, before any sbcx import reads settings.
_TMP = Path(tempfile.mkdtemp(prefix="sbcx-test-"))
os.environ["SBCX_ENV"] = "test"
os.environ["SBCX_VAR_DIR"] = str(_TMP)
os.environ["SBCX_LLM_MODE"] = "fake"
os.environ.setdefault("SBCX_LOG_LEVEL", "WARNING")

REPO = Path(__file__).resolve().parents[2]
GOLD_IDS = sorted(p.stem for p in (REPO / "data/gold/labels").glob("*.json"))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from sbcx.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_db():
    """Every test starts with empty tables (one SQLite file per run, reset per test)."""
    from sbcx.infra.db import Base, get_engine, init_db

    init_db()
    with get_engine().begin() as conn:
        for t in reversed(Base.metadata.sorted_tables):
            conn.execute(t.delete())
    yield
