"""add Local Imoveis source and property offers

Revision ID: 0008_localimoveis_offers
Revises: 0007_property_photo_lifecycle
Create Date: 2026-07-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_localimoveis_offers"
down_revision = "0007_property_photo_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        INSERT INTO sources (id, key, name, base_url, notes, enabled)
        VALUES (
            '00000000-0000-0000-0000-000000000005',
            'localimoveis',
            'Local Imóveis',
            'https://www.localimoveis.com.br',
            'Local Imóveis provider for sale and rent inventory synchronization.',
            true
        )
        ON CONFLICT (key) DO UPDATE
        SET name = EXCLUDED.name,
            base_url = EXCLUDED.base_url,
            enabled = EXCLUDED.enabled
        """
    )

    op.create_table(
        "property_offers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True, server_default="BRL"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("missing_since", sa.DateTime(), nullable=True),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("property_id", "purpose", name="uq_property_offers_property_purpose"),
    )
    op.create_index("ix_property_offers_property_id", "property_offers", ["property_id"])
    op.create_index("ix_property_offers_purpose_status", "property_offers", ["purpose", "status"])


def downgrade():
    op.drop_index("ix_property_offers_purpose_status", table_name="property_offers")
    op.drop_index("ix_property_offers_property_id", table_name="property_offers")
    op.drop_table("property_offers")
    op.execute(
        """
        DELETE FROM sources
        WHERE key = 'localimoveis'
          AND NOT EXISTS (
              SELECT 1
              FROM properties
              WHERE properties.source_id = sources.id
          )
        """
    )
