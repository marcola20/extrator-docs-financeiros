"""Dependências da API: a sessão, e o erro claro quando não há banco.

A sessão vem por `Depends` e não por import direto para o teste poder trocá-la
por uma de SQLite — é o mecanismo que permite testar os endpoints sem subir
Postgres, que é a mesma razão de o resto da fase rodar sem serviço.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.persistencia.sessao import PersistenciaDesligada
from app.persistencia.sessao import sessao as abre_sessao

SEM_BANCO = (
    "esta rota precisa de banco, e a persistência está desligada. "
    "Ligue PERSISTENCIA_ATIVA=1 e aponte DATABASE_URL para um Postgres de pé. "
    "O pipeline e o eval continuam rodando sem banco."
)


def obtem_sessao() -> Iterator[Session]:
    """Uma sessão por requisição, com commit no fim e rollback em erro.

    Traduz `PersistenciaDesligada` em 503 com a instrução: um 500 genérico
    faria parecer defeito da API o que é ambiente sem banco de propósito.
    """
    try:
        with abre_sessao() as aberta:
            yield aberta
    except PersistenciaDesligada as erro:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=SEM_BANCO
        ) from erro


# `Annotated` em vez de `Depends` no valor padrão: é a forma moderna do
# FastAPI, e a que não esbarra na regra que proíbe chamada de função em
# argumento padrão — a regra está certa em geral, e aqui o alias resolve os
# dois lados sem um `noqa`.
SessaoDependente = Annotated[Session, Depends(obtem_sessao)]
