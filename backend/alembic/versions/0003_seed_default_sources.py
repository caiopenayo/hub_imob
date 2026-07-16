"""seed default scraper sources

Revision ID: 0003_seed_default_sources
Revises: 0002_add_jobs_logs
Create Date: 2026-07-01 00:00:00.000000
"""

from alembic import op


revision = "0003_seed_default_sources"
down_revision = "0002_add_jobs_logs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        INSERT INTO sources (id, name, base_url, notes)
        VALUES
            (
                '00000000-0000-0000-0000-000000000001',
                'Example Source',
                'https://example.com',
                'Default source used by the example scraper.'
            ),
            (
                '00000000-0000-0000-0000-000000000002',
                'Idealista',
                'https://www.idealista.it',
                'Default source used by the Idealista scraper.'
            )
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade():
    op.execute(
        """
        DELETE FROM sources
        WHERE id IN (
            '00000000-0000-0000-0000-000000000001',
            '00000000-0000-0000-0000-000000000002'
        )
        """
    )
