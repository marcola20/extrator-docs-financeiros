"""A raiz da API: está no ar, e diz se tem banco por trás."""

import pytest
from fastapi.testclient import TestClient

from app import main as modulo_main
from app.config import Settings
from app.main import app

client = TestClient(app)


def test_health_retorna_ok() -> None:
    resposta = client.get("/health")

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "ok"


def test_health_nao_consulta_o_banco() -> None:
    """Um `/health` que consultasse Postgres reprovaria num ambiente que roda
    sem banco de propósito, e o sintoma seria um orquestrador reiniciando um
    processo saudável. Aqui ele responde sem banco nenhum de pé."""
    resposta = client.get("/health")

    assert resposta.status_code == 200


def test_health_reflete_a_configuracao(monkeypatch: pytest.MonkeyPatch) -> None:
    """O que ele reporta vem da configuração, e não de um literal.

    Afirmar `False` direto passaria a testar o ambiente da máquina em vez do
    endpoint — foi assim que estes testes reprovaram com `PERSISTENCIA_ATIVA=1`
    exportado.
    """
    monkeypatch.setattr(
        modulo_main, "get_settings", lambda: Settings(_env_file=None, persistencia_ativa=True)
    )

    assert client.get("/health").json()["persistencia"] is True


def test_as_rotas_de_revisao_estao_no_contrato() -> None:
    """Confere pelo OpenAPI, que é o que a tela vai ler para gerar o cliente."""
    caminhos = set(client.get("/openapi.json").json()["paths"])

    assert {
        "/revisao/fila",
        "/revisao/estatisticas",
        "/revisao/{decisao_id}",
        "/revisao/{decisao_id}/pdf",
        "/revisao/{decisao_id}/correcoes",
    } <= caminhos


def test_health_diz_o_que_esta_ligado() -> None:
    """Os dois opcionais da Fase 4, visíveis sem abrir a configuração."""
    corpo = client.get("/health").json()

    assert isinstance(corpo["persistencia"], bool)
    assert isinstance(corpo["observabilidade"], bool)


def test_o_middleware_de_trace_nao_atrapalha_sem_langfuse() -> None:
    """Sem chave o observador é mudo, e o middleware custa uma chamada vazia."""
    assert client.get("/health").status_code == 200
    assert client.get("/revisao/99999").status_code in (404, 503)
