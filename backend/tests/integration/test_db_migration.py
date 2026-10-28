"""init_db adds columns introduced after a database was created (no migration tool yet)."""

from sqlalchemy import inspect, text


def test_init_db_adds_hsa_eligible_to_an_old_catalog_table():
    from sbcx.infra.db import get_engine, init_db

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE catalog_plans DROP COLUMN hsa_eligible"))
    assert "hsa_eligible" not in {c["name"] for c in inspect(engine).get_columns("catalog_plans")}
    init_db()
    assert "hsa_eligible" in {c["name"] for c in inspect(engine).get_columns("catalog_plans")}
    init_db()  # idempotent
