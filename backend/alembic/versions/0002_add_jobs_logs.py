"""add jobs_logs table

Revision ID: 0002_add_jobs_logs
Revises: 0001_create_properties
Create Date: 2026-06-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0002_add_jobs_logs'
down_revision = '0001_create_properties'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'jobs_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('job_name', sa.String(length=255), nullable=False),
        sa.Column('source_ids', postgresql.JSONB(), nullable=True),
        sa.Column('mode', sa.String(length=20), nullable=False, server_default='delta'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('started_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('finished_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('summary', postgresql.JSONB(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()')),
    )


def downgrade():
    op.drop_table('jobs_logs')
