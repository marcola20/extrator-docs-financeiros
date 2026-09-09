"""Ponto de entrada da API.

A rota de saúde não toca no banco de propósito: ela responde se o processo está
de pé, e um `/health` que consultasse Postgres passaria a reprovar num ambiente
que roda sem banco — que é o modo padrão desta fase.
"""

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel

from app.api.demo import roteador as roteador_da_demonstracao
from app.api.dependencias import ConfiguracaoDependente
from app.api.revisao import roteador as roteador_de_revisao
from app.observabilidade import observador

app = FastAPI(
    title="Extrator de Documentos Financeiros",
    version="0.1.0",
    summary="Extração com validação determinística e fila de revisão humana",
)
app.include_router(roteador_de_revisao)
app.include_router(roteador_da_demonstracao)

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

    somente_leitura: bool
    """Se esta instância é a demonstração pública, que recusa gravar correção."""


@app.get("/health")
def health(settings: ConfiguracaoDependente) -> HealthResponse:
    """Indica que a API está no ar, e o que ela tem ligado por trás.

    A configuração entra por `Depends` e não por `get_settings()` direto: sem
    isso, um teste que troca a configuração da aplicação inteira veria esta rota
    responder o contrário do que as outras respondem — e é uma rota de
    diagnóstico, o pior lugar para uma resposta que não descreve a instância.
    """
    return HealthResponse(
        status="ok",
        persistencia=settings.persistencia_ativa,
        observabilidade=_observador.ativo,
        somente_leitura=settings.demo_somente_leitura,
    )
