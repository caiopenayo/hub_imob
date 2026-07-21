"""add property photo lifecycle fields

Revision ID: 0007_property_photo_lifecycle
Revises: 0006_rename_zimmermann_source_key
Create Date: 2026-07-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_property_photo_lifecycle"
down_revision = "0006_rename_zim_key"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "property_photos",
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("true")),
    )
    op.add_column("property_photos", sa.Column("removed_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE property_photos SET is_active = true WHERE is_active IS NULL")


def downgrade():
    op.drop_column("property_photos", "removed_at")
    op.drop_column("property_photos", "is_active")
