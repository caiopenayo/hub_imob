"""seed Pacheco Imoveis source

Revision ID: 0009_seed_pacheco_source
Revises: 0008_localimoveis_offers
Create Date: 2026-07-17 00:00:00.000000
"""

from alembic import op


revision = "0009_seed_pacheco_source"
down_revision = "0008_localimoveis_offers"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        INSERT INTO sources (id, key, name, base_url, notes, enabled)
        VALUES (
            '00000000-0000-0000-0000-000000000006',
            'pacheco',
            'Pacheco Imóveis',
            'https://pacheco.com.br',
            'Pacheco provider for sale and rent inventory synchronization.',
            true
        )
        ON CONFLICT (key) DO UPDATE
        SET name = EXCLUDED.name,
            base_url = EXCLUDED.base_url,
            enabled = EXCLUDED.enabled
        """
    )


def downgrade():
    op.execute(
        """
        DELETE FROM sources
        WHERE key = 'pacheco'
          AND NOT EXISTS (
              SELECT 1
              FROM properties
              WHERE properties.source_id = sources.id
          )
        """
    )
