"""remove Professionecasa test source from active inventory

Revision ID: 0010_remove_professionecasa
Revises: 0009_seed_pacheco_source
Create Date: 2026-07-21 00:00:00.000000
"""

from alembic import op


revision = "0010_remove_professionecasa"
down_revision = "0009_seed_pacheco_source"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DELETE FROM properties
        WHERE source_id IN (
            SELECT id
            FROM sources
            WHERE key = 'professionecasa'
        )
        """
    )
    op.execute(
        """
        UPDATE sources
        SET enabled = false,
            notes = 'Disabled: temporary Turin test scraper removed from the product inventory.'
        WHERE key = 'professionecasa'
        """
    )


def downgrade():
    op.execute(
        """
        UPDATE sources
        SET enabled = true,
            notes = 'Default source used by the Professionecasa scraper.'
        WHERE key = 'professionecasa'
        """
    )
