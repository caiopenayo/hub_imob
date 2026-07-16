"""add shared scraping framework storage

Revision ID: 0005_scraping_framework
Revises: 0004_seed_professionecasa_source
Create Date: 2026-07-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_scraping_framework"
down_revision = "0004_seed_professionecasa_source"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sources", sa.Column("key", sa.String(length=100), nullable=True))
    op.add_column("sources", sa.Column("enabled", sa.Boolean(), nullable=True, server_default=sa.text("true")))
    op.create_unique_constraint("uq_sources_key", "sources", ["key"])
    op.execute(
        """
        UPDATE sources
        SET key = CASE
            WHEN id = '00000000-0000-0000-0000-000000000001' THEN 'example'
            WHEN id = '00000000-0000-0000-0000-000000000002' THEN 'idealista'
            WHEN id = '00000000-0000-0000-0000-000000000003' THEN 'professionecasa'
            ELSE key
        END
        WHERE key IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO sources (id, key, name, base_url, notes, enabled)
        VALUES (
            '00000000-0000-0000-0000-000000000004',
            'zimmermann',
            'Zimmermann Imóveis',
            'https://www.zimoveis.com.br',
            'Provider skeleton for the shared scraper framework.',
            true
        )
        ON CONFLICT (id) DO NOTHING
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'properties' AND column_name = 'metadata'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'properties' AND column_name = 'metadata_json'
            ) THEN
                ALTER TABLE properties RENAME COLUMN metadata TO metadata_json;
            END IF;
        END $$;
        """
    )

    op.add_column("properties", sa.Column("source_url", sa.Text(), nullable=True))
    op.add_column("properties", sa.Column("transaction_type", sa.String(length=50), nullable=True))
    op.add_column("properties", sa.Column("property_type", sa.String(length=100), nullable=True))
    op.add_column("properties", sa.Column("property_subtype", sa.String(length=100), nullable=True))
    op.add_column("properties", sa.Column("condominium_fee", sa.Numeric(12, 2), nullable=True))
    op.add_column("properties", sa.Column("property_tax", sa.Numeric(12, 2), nullable=True))
    op.add_column("properties", sa.Column("price_per_m2", sa.Numeric(12, 2), nullable=True))
    op.add_column("properties", sa.Column("suites", sa.Integer(), nullable=True))
    op.add_column("properties", sa.Column("parking_spaces", sa.Integer(), nullable=True))
    op.add_column("properties", sa.Column("main_image_url", sa.Text(), nullable=True))
    op.add_column("properties", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.add_column("properties", sa.Column("missing_since", sa.DateTime(), nullable=True))
    op.add_column("properties", sa.Column("removed_at", sa.DateTime(), nullable=True))
    op.add_column("properties", sa.Column("detail_last_fetched_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE properties SET source_url = url WHERE source_url IS NULL")
    op.execute(
        """
        UPDATE properties
        SET status = CASE
            WHEN lower(status) = 'missing' THEN 'MISSING'
            WHEN lower(status) = 'removed' THEN 'REMOVED'
            ELSE 'ACTIVE'
        END
        WHERE status IS NOT NULL
        """
    )
    op.drop_index("ix_properties_source_external", table_name="properties")
    op.create_unique_constraint("uq_properties_source_external", "properties", ["source_id", "external_id"])
    op.create_index("ix_properties_status", "properties", ["status"])
    op.create_index("ix_properties_content_hash", "properties", ["content_hash"])

    op.create_table(
        "property_photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.UniqueConstraint("property_id", "source_url", name="uq_property_photos_property_source_url"),
    )

    op.create_table(
        "property_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("old_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("crawl_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs_logs.id"), nullable=True),
    )
    op.create_index("ix_property_events_property_id", "property_events", ["property_id"])
    op.create_index("ix_property_events_event_type", "property_events", ["event_type"])

    op.add_column("jobs_logs", sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("jobs_logs", sa.Column("provider_key", sa.String(length=100), nullable=True))
    op.add_column("jobs_logs", sa.Column("search_scope", postgresql.JSONB(), nullable=True))
    op.add_column("jobs_logs", sa.Column("pages_fetched", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("jobs_logs", sa.Column("listings_seen", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("jobs_logs", sa.Column("new_properties", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("jobs_logs", sa.Column("updated_properties", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("jobs_logs", sa.Column("unchanged_properties", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("jobs_logs", sa.Column("missing_properties", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("jobs_logs", sa.Column("removed_properties", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("jobs_logs", sa.Column("reactivated_properties", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("jobs_logs", sa.Column("detail_pages_fetched", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("jobs_logs", sa.Column("http_errors", postgresql.JSONB(), nullable=True))
    op.add_column("jobs_logs", sa.Column("parse_errors", postgresql.JSONB(), nullable=True))
    op.create_foreign_key("fk_jobs_logs_source_id_sources", "jobs_logs", "sources", ["source_id"], ["id"])


def downgrade():
    op.drop_constraint("fk_jobs_logs_source_id_sources", "jobs_logs", type_="foreignkey")
    op.drop_column("jobs_logs", "parse_errors")
    op.drop_column("jobs_logs", "http_errors")
    op.drop_column("jobs_logs", "detail_pages_fetched")
    op.drop_column("jobs_logs", "reactivated_properties")
    op.drop_column("jobs_logs", "removed_properties")
    op.drop_column("jobs_logs", "missing_properties")
    op.drop_column("jobs_logs", "unchanged_properties")
    op.drop_column("jobs_logs", "updated_properties")
    op.drop_column("jobs_logs", "new_properties")
    op.drop_column("jobs_logs", "listings_seen")
    op.drop_column("jobs_logs", "pages_fetched")
    op.drop_column("jobs_logs", "search_scope")
    op.drop_column("jobs_logs", "provider_key")
    op.drop_column("jobs_logs", "source_id")

    op.drop_index("ix_property_events_event_type", table_name="property_events")
    op.drop_index("ix_property_events_property_id", table_name="property_events")
    op.drop_table("property_events")
    op.drop_table("property_photos")

    op.drop_index("ix_properties_content_hash", table_name="properties")
    op.drop_index("ix_properties_status", table_name="properties")
    op.drop_constraint("uq_properties_source_external", "properties", type_="unique")
    op.create_index("ix_properties_source_external", "properties", ["source_id", "external_id"], unique=False)
    op.drop_column("properties", "detail_last_fetched_at")
    op.drop_column("properties", "removed_at")
    op.drop_column("properties", "missing_since")
    op.drop_column("properties", "content_hash")
    op.drop_column("properties", "main_image_url")
    op.drop_column("properties", "parking_spaces")
    op.drop_column("properties", "suites")
    op.drop_column("properties", "price_per_m2")
    op.drop_column("properties", "property_tax")
    op.drop_column("properties", "condominium_fee")
    op.drop_column("properties", "property_subtype")
    op.drop_column("properties", "property_type")
    op.drop_column("properties", "transaction_type")
    op.drop_column("properties", "source_url")

    op.execute("DELETE FROM sources WHERE key = 'zimmermann'")
    op.drop_constraint("uq_sources_key", "sources", type_="unique")
    op.drop_column("sources", "enabled")
    op.drop_column("sources", "key")
