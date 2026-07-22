"""add balcony field and neighborhood search index

Revision ID: 0011_property_balcony_search
Revises: 0010_remove_professionecasa
Create Date: 2026-07-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_property_balcony_search"
down_revision = "0010_remove_professionecasa"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("properties", sa.Column("balcony", sa.Boolean(), nullable=True))
    op.create_index("ix_properties_neighborhood", "properties", ["neighborhood"])


def downgrade():
    op.drop_index("ix_properties_neighborhood", table_name="properties")
    op.drop_column("properties", "balcony")
