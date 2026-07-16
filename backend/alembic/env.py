from logging.config import fileConfig

import asyncio

from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from alembic import context

import os
import sys

# Adiciona a raiz do projeto ao path do Python
# Isso permite importar arquivos do backend dentro do ambiente do Alembic
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importa a Base do SQLAlchemy, que contém os metadados das tabelas
from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: E402
from app.core.config import ASYNC_DATABASE_URL  # noqa: E402


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Executa migrations em modo offline
# Nesse modo, Alembic gera SQL sem abrir conexão direta com o banco
def run_migrations_offline():
    url = ASYNC_DATABASE_URL
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    section = config.get_section(config.config_ini_section)

    if section is None:
        raise RuntimeError("Alembic config section not found")

    section["sqlalchemy.url"] = ASYNC_DATABASE_URL

    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"statement_cache_size": 0},
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


# Executa migrations em modo online
# Nesse modo, Alembic conecta diretamente no banco e aplica as alterações
def run_migrations_online():
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
