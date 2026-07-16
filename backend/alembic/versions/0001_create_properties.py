"""create properties and sources tables

igration Alembic responsável por criar as tabelas iniciais do banco:
- sources: fontes dos anúncios, como imobiliárias/sites
- properties: imóveis coletados dessas fontes

Também cria índices para acelerar buscas por cidade, preço e fonte + ID externo.

Revision ID: 0001_create_properties
Revises: 
Create Date: 2026-06-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0001_create_properties'
# Como é a primeira migration, ela não depende de nenhuma anterior
down_revision = None
branch_labels = None
# Usado para declarar dependência de outra migration específica; aqui não há
depends_on = None

# Função executada quando rodamos: alembic upgrade
def upgrade():
        # Cria a tabela sources, que guarda as fontes dos anúncios
    op.create_table(
        'sources',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('base_url', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )
    # Cria a tabela properties, que guarda os imóveis coletados
    op.create_table(
        'properties',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('external_id', sa.String(length=255), nullable=False),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sources.id'), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price', sa.Numeric(12, 2), nullable=True),
        sa.Column('price_currency', sa.String(length=3), server_default='BRL'),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('address_line', sa.Text(), nullable=True),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('neighborhood', sa.String(length=255), nullable=True),
        sa.Column('state', sa.String(length=100), nullable=True),
        sa.Column('postal_code', sa.String(length=20), nullable=True),
        sa.Column('country', sa.String(length=50), server_default='BR'),
        sa.Column('latitude', sa.Numeric(9, 6), nullable=True),
        sa.Column('longitude', sa.Numeric(9, 6), nullable=True),
        sa.Column('bedrooms', sa.Integer(), nullable=True),
        sa.Column('bathrooms', sa.Integer(), nullable=True),
        sa.Column('area_m2', sa.Numeric(8, 2), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='active'),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=True),
        sa.Column('first_seen_at', sa.TIMESTAMP(), server_default=sa.text('now()')),
        sa.Column('last_seen_at', sa.TIMESTAMP(), server_default=sa.text('now()')),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('now()')),
    )
    # Cria índice para acelerar filtros por cidade
    op.create_index('ix_properties_city', 'properties', ['city'])
    op.create_index('ix_properties_price', 'properties', ['price'])
    op.create_index('ix_properties_source_external', 'properties', ['source_id', 'external_id'], unique=False)


# Função executada quando rodamos: alembic downgrade
def downgrade():
    # Remove o índice de fonte + ID externo
    op.drop_index('ix_properties_source_external', table_name='properties')
    op.drop_index('ix_properties_price', table_name='properties')
    op.drop_index('ix_properties_city', table_name='properties')
    op.drop_table('properties')
    op.drop_table('sources')
