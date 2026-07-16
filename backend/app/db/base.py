"""
Este arquivo define a classe base do SQLAlchemy.

Todos os modelos do banco de dados (ex.: Property, Source, JobLog)
devem herdar desta classe para que o SQLAlchemy consiga:

- mapear classes Python para tabelas do banco;
- criar e gerenciar o esquema do banco;
- registrar automaticamente os modelos na aplicação.

Exemplo:
    class Property(Base):
        __tablename__ = "properties"
        ...
"""

from sqlalchemy.orm import declarative_base

Base = declarative_base()
