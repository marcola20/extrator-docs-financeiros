"""Ponto de entrada da API."""

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Extrator de Documentos Financeiros", version="0.1.0")


class HealthResponse(BaseModel):
    """Resposta do endpoint de saúde."""

    status: str


@app.get("/health")
def health() -> HealthResponse:
    """Indica que a API está no ar."""
    return HealthResponse(status="ok")
