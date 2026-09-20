"""Test configuration.

Database selection: prefer the real local PostgreSQL 16
(ai_cost_doctor_test). If unreachable, fall back to a file-backed SQLite DB
and skip Postgres-only tests (RLS). The selected backend is printed at
session start so reports are unambiguous.
"""
from __future__ import annotations

import os
import sys

# --- Choose the database BEFORE importing any app modules -----------------
PG_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://aicostdoctor:dev-local-only@localhost:5432/ai_cost_doctor_test",
)
SQLITE_PATH = "/tmp/aicostdoctor_test.db"


def _pg_reachable(url: str) -> bool:
    try:
        from sqlalchemy import create_engine, text
        eng = create_engine(url, connect_args={"connect_timeout": 3})
        with eng.connect() as c:
            c.execute(text("select 1"))
        eng.dispose()
        return True
    except Exception:
        return False


if _pg_reachable(PG_URL):
    os.environ["DATABASE_URL"] = PG_URL
    DB_BACKEND = "postgresql"
else:  # pragma: no cover - exercised only when PG is unavailable
    if os.path.exists(SQLITE_PATH):
        os.remove(SQLITE_PATH)
    os.environ["DATABASE_URL"] = f"sqlite:///{SQLITE_PATH}"
    DB_BACKEND = "sqlite"

print(f"\n[tests] database backend: {DB_BACKEND} ({os.environ['DATABASE_URL'].split('@')[-1]})")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.db import Base  # noqa: E402
import app.models  # noqa: E402,F401
from app.core.db import get_db  # noqa: E402


def _fresh_schema(url: str) -> None:
    """Wipe and rebuild the schema via Alembic (exercises the real migrations)."""
    if url.startswith("postgresql"):
        from sqlalchemy import create_engine as ce
        eng = ce(url)
        with eng.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE"))
            c.execute(text("CREATE SCHEMA public"))
        eng.dispose()
        import alembic.config
        cfg = alembic.config.Config(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alembic.ini"))
        from alembic import command
        command.upgrade(cfg, "head")
    else:  # sqlite fallback
        eng = create_engine(url)
        Base.metadata.create_all(eng)
        eng.dispose()


@pytest.fixture(scope="session")
def db_url():
    _fresh_schema(os.environ["DATABASE_URL"])
    return os.environ["DATABASE_URL"]


@pytest.fixture()
def db(db_url):
    """Function-scoped session with transaction rollback isolation.

    NOTE: tests that call endpoints which COMMIT (e.g. /demo/seed) must do
    their own cleanup — rollback cannot undo a committed transaction.
    """
    engine = create_engine(db_url, connect_args=({"check_same_thread": False}
                                                 if db_url.startswith("sqlite") else {}))
    conn = engine.connect()
    txn = conn.begin()
    session = sessionmaker(bind=conn, expire_on_commit=False)()
    yield session
    session.close()
    txn.rollback()
    conn.close()
    engine.dispose()


@pytest.fixture()
def client(db_url):
    """TestClient with get_db overridden to a fresh session per test."""
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app

    engine = create_engine(db_url, connect_args=({"check_same_thread": False}
                                                 if db_url.startswith("sqlite") else {}))
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()
    engine.dispose()


requires_pg = pytest.mark.skipif(
    DB_BACKEND != "postgresql",
    reason="Postgres-only test (RLS / citext / numeric behaviours)",
)
