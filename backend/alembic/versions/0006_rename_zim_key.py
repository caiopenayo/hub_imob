"""rename Zimmermann source key to zimoveis

Revision ID: 0006_rename_zimmermann_source_key
Revises: 0005_scraping_framework
Create Date: 2026-07-16 00:00:00.000000
"""

from alembic import op


revision = "0006_rename_zim_key"
down_revision = "0005_scraping_framework"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        DECLARE
            old_id uuid;
            new_id uuid;
        BEGIN
            SELECT id INTO old_id FROM sources WHERE key = 'zimmermann' LIMIT 1;
            SELECT id INTO new_id FROM sources WHERE key = 'zimoveis' LIMIT 1;

            IF old_id IS NOT NULL AND new_id IS NOT NULL AND old_id <> new_id THEN
                UPDATE properties SET source_id = new_id WHERE source_id = old_id;
                UPDATE jobs_logs SET source_id = new_id WHERE source_id = old_id;
                DELETE FROM sources WHERE id = old_id;
            ELSIF old_id IS NOT NULL THEN
                UPDATE sources
                SET key = 'zimoveis',
                    name = 'Zimmermann Imóveis',
                    base_url = 'https://www.zimoveis.com.br'
                WHERE id = old_id;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        INSERT INTO sources (id, key, name, base_url, notes, enabled)
        VALUES (
            '00000000-0000-0000-0000-000000000004',
            'zimoveis',
            'Zimmermann Imóveis',
            'https://www.zimoveis.com.br',
            'Zimmermann Imóveis provider for the shared scraper framework.',
            true
        )
        ON CONFLICT (key) DO UPDATE
        SET name = EXCLUDED.name,
            base_url = EXCLUDED.base_url,
            enabled = EXCLUDED.enabled
        """
    )


def downgrade():
    op.execute("UPDATE sources SET key = 'zimmermann' WHERE key = 'zimoveis'")
