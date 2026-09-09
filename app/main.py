"""Ponto de entrada da API.

A rota de saúde não toca no banco de propósito: ela responde se o processo está
de pé, e um `/health` que consultasse Postgres passaria a reprovar num ambiente
que roda sem banco — que é o modo padrão desta fase.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from app.api.revisao import roteador as roteador_de_revisao
from app.config import get_settings

app = FastAPI(
    title="Extrator de Documentos Financeiros",
    version="0.1.0",
    summary="Extração com validação determinística e fila de revisão humana",
)
app.include_router(roteador_de_revisao)


class HealthResponse(BaseModel):
    """Resposta do endpoint de saúde."""

    status: str
    persistencia: bool
    """Se a fila de revisão está disponível neste ambiente."""


@app.get("/health")
def health() -> HealthResponse:
    """Indica que a API está no ar, e se ela tem banco por trás."""
    return HealthResponse(status="ok", persistencia=get_settings().persistencia_ativa)
