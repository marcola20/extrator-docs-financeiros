"""A raiz da API: está no ar, e diz se tem banco por trás."""

import subprocess
import sys
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
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


@pytest.fixture
def configuracao_trocada() -> Iterator[None]:
    """Troca a configuração da aplicação pela via oficial: `dependency_overrides`.

    Antes isto era um `monkeypatch` no `get_settings` importado por `app.main`,
    e parou de funcionar quando a rota passou a receber a configuração por
    `Depends` — que é o que faz `/health` descrever a mesma instância que as
    outras rotas enxergam.
    """
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, persistencia_ativa=True, demo_somente_leitura=True
    )
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_health_reflete_a_configuracao(configuracao_trocada: None) -> None:
    """O que ele reporta vem da configuração, e não de um literal.

    Afirmar `False` direto passaria a testar o ambiente da máquina em vez do
    endpoint — foi assim que estes testes reprovaram com `PERSISTENCIA_ATIVA=1`
    exportado.
    """
    corpo = client.get("/health").json()

    assert corpo["persistencia"] is True
    assert corpo["somente_leitura"] is True


def test_as_rotas_de_revisao_estao_no_contrato() -> None:
    """Confere pelo OpenAPI, que é o que a tela vai ler para gerar o cliente."""
    caminhos = set(client.get("/openapi.json").json()["paths"])

    assert {
        "/revisao/fila",
        "/revisao/estatisticas",
        "/revisao/{decisao_id}",
        "/revisao/{decisao_id}/pdf",
        "/revisao/{decisao_id}/correcoes",
        "/demo/casos",
    } <= caminhos


def test_health_diz_o_que_esta_ligado() -> None:
    """Os dois opcionais da Fase 4, visíveis sem abrir a configuração."""
    corpo = client.get("/health").json()

    assert isinstance(corpo["persistencia"], bool)
    assert isinstance(corpo["observabilidade"], bool)
    assert isinstance(corpo["somente_leitura"], bool)


def test_o_middleware_de_trace_nao_atrapalha_sem_langfuse() -> None:
    """Sem chave o observador é mudo, e o middleware custa uma chamada vazia."""
    assert client.get("/health").status_code == 200
    assert client.get("/revisao/99999").status_code in (404, 503)


def test_importar_a_api_nao_carrega_o_pipeline() -> None:
    """A promessa que o Dockerfile faz, conferida em vez de afirmada.

    A API não processa documento: ela lê o banco e serve arquivo. Se um import
    novo trouxer pdfplumber, PIL ou um SDK de provedor para dentro dela, a
    imagem engorda e — pior — a fronteira que separa "servir" de "processar"
    deixa de existir sem ninguém perceber.

    Foi o risco que a Fase 4.3 acrescentou: `app/demo.py` entrou no grafo de
    imports da API, e a tentação de reusar `app.persistencia.gravacao` ali era
    real. Ele traz os quatro (medido).

    Num subprocesso porque `sys.modules` é do processo inteiro: rodando junto
    com a suíte, tudo isto já foi importado por outro teste.
    """
    codigo = (
        "import sys; import app.main; "
        "print(','.join(sorted({'pdfplumber','pypdfium2','weasyprint','PIL',"
        "'google','anthropic','pytesseract'} & "
        "{m.split('.')[0] for m in sys.modules})))"
    )
    saida = subprocess.run(
        [sys.executable, "-c", codigo], capture_output=True, text=True, check=True
    )

    assert saida.stdout.strip() == "", (
        f"importar app.main carregou {saida.stdout.strip()}. A API não processa "
        f"documento; ver a nota do Dockerfile e o ADR 012."
    )
