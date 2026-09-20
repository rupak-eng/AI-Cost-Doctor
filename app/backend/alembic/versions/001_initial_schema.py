"""Initial schema: all tables per specs/02-architecture.md §3 + tenants.

Tables are created from the SQLAlchemy metadata (single source of truth for
v0.1); the pricing catalog JSON is then loaded as data.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy.orm import Session

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    from app.core.db import Base
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=bind)

    # Seed the versioned pricing catalog (idempotent).
    from app.services import costing
    session = Session(bind=bind)
    try:
        costing.ensure_catalog_in_db(session, costing.load_catalog())
        session.commit()
    finally:
        session.close()


def downgrade() -> None:
    from app.core.db import Base
    import app.models  # noqa: F401

    Base.metadata.drop_all(bind=op.get_bind())
