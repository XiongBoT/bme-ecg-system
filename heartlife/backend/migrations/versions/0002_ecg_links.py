"""Add private, user-scoped ECG bridge credentials.

Revision ID: 0002_ecg_links
Revises: 0001_initial_schema
"""
from alembic import op
from app.db.models import EcgLink

revision = "0002_ecg_links"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Initial revision uses live Base metadata; fresh installs already have this table.
    EcgLink.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    EcgLink.__table__.drop(bind=op.get_bind(), checkfirst=True)
