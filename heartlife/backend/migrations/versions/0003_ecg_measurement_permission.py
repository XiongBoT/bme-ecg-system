"""Keep existing ECG bindings read-only when measurement support is added.

Revision ID: 0003_ecg_measurement_permission
Revises: 0002_ecg_links
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_ecg_measurement_permission"
down_revision = "0002_ecg_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Earlier revisions use live metadata, so fresh installations already have it.
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("ecg_links")}
    if "measurement_allowed" not in columns:
        op.add_column("ecg_links", sa.Column("measurement_allowed", sa.Boolean(),
                                            nullable=False, server_default=sa.false()))


def downgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("ecg_links")}
    if "measurement_allowed" in columns:
        with op.batch_alter_table("ecg_links") as batch:
            batch.drop_column("measurement_allowed")
