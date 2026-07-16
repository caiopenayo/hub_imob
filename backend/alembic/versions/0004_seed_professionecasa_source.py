"""seed professionecasa scraper source

Revision ID: 0004_seed_professionecasa_source
Revises: 0003_seed_default_sources
Create Date: 2026-07-03 00:00:00.000000
"""

from alembic import op


revision = "0004_seed_professionecasa_source"
down_revision = "0003_seed_default_sources"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        INSERT INTO sources (id, name, base_url, notes)
        VALUES (
            '00000000-0000-0000-0000-000000000003',
            'Professionecasa',
            'https://www.professionecasa.it',
            'Default source used by the Professionecasa scraper.'
        )
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade():
    op.execute(
        """
        DELETE FROM sources
        WHERE id = '00000000-0000-0000-0000-000000000003'
        """
    )
