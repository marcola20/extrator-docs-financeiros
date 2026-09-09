"""Ponto de entrada da API.

A rota de saúde não toca no banco de propósito: ela responde se o processo está
de pé, e um `/health` que consultasse Postgres passaria a reprovar num ambiente
que roda sem banco — que é o modo padrão desta fase.
"""

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel

from app.api.revisao import roteador as roteador_de_revisao
from app.config import get_settings
from app.observabilidade import observador

app = FastAPI(
    title="Extrator de Documentos Financeiros",
    version="0.1.0",
    summary="Extração com validação determinística e fila de revisão humana",
)
app.include_router(roteador_de_revisao)

_observador = observador()


@app.middleware("http")
async def observa_requisicao(
    requisicao: Request, chamar: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Um trecho por requisição, com latência e status.

    Sem Langfuse configurado o observador é mudo e este middleware custa uma
    chamada de função vazia — é o que permite deixá-lo montado sempre em vez de
    condicionar a montagem do app à configuração.

    O corpo não é anotado: uma requisição de correção carrega o valor que o
    revisor digitou, que é conteúdo de documento real. O painel de traces não é
    lugar para isso, pela mesma razão que ele não entra no git.
    """
    inicio = time.monotonic()
    with _observador.trecho(
        "requisicao", metodo=requisicao.method, rota=requisicao.url.path
    ) as trecho:
        resposta = await chamar(requisicao)
        trecho.anota(
            status=resposta.status_code,
            latencia_s=round(time.monotonic() - inicio, 3),
        )
    return resposta


class HealthResponse(BaseModel):
    """Resposta do endpoint de saúde."""

    status: str
    persistencia: bool
    """Se a fila de revisão está disponível neste ambiente."""

    observabilidade: bool
    """Se os traces estão indo para algum lugar."""


@app.get("/health")
def health() -> HealthResponse:
    """Indica que a API está no ar, e o que ela tem ligado por trás."""
    return HealthResponse(
        status="ok",
        persistencia=get_settings().persistencia_ativa,
        observabilidade=_observador.ativo,
    )
