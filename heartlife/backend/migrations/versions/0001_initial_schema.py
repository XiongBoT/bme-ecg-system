"""Initial HeartLife independent schema

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-11-26 12:00:00
"""
from __future__ import annotations

from alembic import op
from app.db.database import Base
import app.db.models  # noqa: F401

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    # Create FTS5 virtual table for fast local Encyclopedia retrieval (EPIC-09)
    bind.exec_driver_sql(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
            article_id UNINDEXED,
            title,
            summary,
            category,
            body
        );
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("DROP TABLE IF EXISTS articles_fts;")
    Base.metadata.drop_all(bind=bind, checkfirst=True)
