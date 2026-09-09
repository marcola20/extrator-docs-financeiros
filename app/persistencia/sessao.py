"""Engine e sessão, criadas sob demanda e só quando a persistência está ligada.

O módulo não abre conexão ao ser importado. Isso importa mais do que parece:
`app.persistencia` é importado pela API, que é importada pelos testes, que
rodam no CI sem Postgres nenhum. Um engine criado no import faria a suíte
inteira depender de um serviço que a Fase 4 decidiu manter opcional.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings


class PersistenciaDesligada(RuntimeError):
    """Alguém pediu banco num ambiente que roda sem banco.

    A mensagem diz qual variável ligar. O erro que ela substitui — uma
    `OperationalError` de conexão recusada, três camadas abaixo — não diz.
    """


def _confere_ligada(settings: Settings) -> None:
    if not settings.persistencia_ativa:
        raise PersistenciaDesligada(
            "a persistência está desligada; ligue PERSISTENCIA_ATIVA=1 e aponte "
            "DATABASE_URL para um Postgres de pé. O pipeline e o eval rodam sem "
            "banco de propósito — só a fila de revisão precisa dele."
        )


def cria_engine(settings: Settings | None = None) -> Engine:
    """Um engine novo. `pool_pre_ping` porque a conexão dorme entre revisões."""
    settings = settings if settings is not None else get_settings()
    _confere_ligada(settings)
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


def cria_fabrica_de_sessao(settings: Settings | None = None) -> sessionmaker[Session]:
    """Fábrica de sessões sobre um engine novo.

    `expire_on_commit=False` de propósito: os endpoints leem o objeto **depois**
    de gravar, para montar a resposta, e com o padrão do SQLAlchemy cada leitura
    dispararia um SELECT novo — ou um `DetachedInstanceError` fora da sessão.
    """
    return sessionmaker(bind=cria_engine(settings), expire_on_commit=False, future=True)


@lru_cache
def _fabrica_padrao() -> sessionmaker[Session]:
    """A fábrica do processo, montada na primeira vez que alguém pede sessão."""
    return cria_fabrica_de_sessao()


@contextmanager
def sessao() -> Iterator[Session]:
    """Uma sessão transacional: commit no fim, rollback em qualquer exceção."""
    with _fabrica_padrao()() as aberta:
        try:
            yield aberta
            aberta.commit()
        except Exception:
            aberta.rollback()
            raise
