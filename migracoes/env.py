"""Ambiente do Alembic: a URL vem da configuração da aplicação, não do .ini.

`alembic.ini` fica sem `sqlalchemy.url` de propósito. Duplicar a URL ali seria
convidar os dois a divergirem — e a divergência aparece como migração aplicada
no banco errado, que é o pior lugar para descobrir uma configuração duplicada.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.persistencia.modelos import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _url() -> str:
    """A URL a migrar: quem chamou tem precedência sobre a configuração.

    Normalmente ninguém passa nada e a URL vem de `DATABASE_URL`. Quem passa é
    o teste que aplica as migrações a um SQLite temporário para comparar o
    schema resultante com os modelos — sem esta precedência ele tentaria
    conectar no Postgres de desenvolvimento, e a conferência viraria um teste
    que só roda na máquina de quem tem o banco de pé.
    """
    escolhida = config.get_main_option("sqlalchemy.url")
    return escolhida or get_settings().database_url


config.set_main_option("sqlalchemy.url", _url())

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Gera o SQL sem conectar. Útil para revisar a migração antes de aplicá-la."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Aplica as migrações contra o banco configurado."""
    conectavel = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with conectavel.connect() as conexao:
        context.configure(
            connection=conexao,
            target_metadata=target_metadata,
            # Sem isto, mudar `String(40)` para `String(80)` não gera migração
            # nenhuma e a coluna fica menor que o modelo, em silêncio.
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
