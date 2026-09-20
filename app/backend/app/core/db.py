"""SQLAlchemy engine / session factory / declarative base."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = settings.database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        # SQLite is for tests/local fallback only; keep it single-threaded safe.
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = _make_engine()

# expire_on_commit=False: after commit(), ORM attribute access must not issue
# fresh SELECTs — important because RLS context (SET LOCAL) is dropped on
# commit and a re-SELECT would come back empty under FORCE ROW LEVEL SECURITY.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                            expire_on_commit=False)


def get_db():
    """FastAPI dependency: request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
