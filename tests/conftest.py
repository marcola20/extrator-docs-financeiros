"""Fixtures de banco e de API para a suíte inteira, em SQLite.

A sessão entra por `Depends` justamente para isto: o teste troca a dependência
e os endpoints não sabem a diferença. É o mesmo motivo de o resto da fase rodar
sem serviço — o CI não tem Postgres, e fazer a suíte depender de um contraria a
decisão de que persistência é opcional.

Ficam na raiz de `tests/` porque dois pacotes precisam delas: os testes da API
e os da realimentação, que exporta a partir do mesmo banco.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencias import obtem_sessao
from app.config import Settings, get_settings
from app.main import app
from app.persistencia.modelos import Base

# Variáveis que a aplicação lê e que, vindas do ambiente, mudariam o resultado
# dos testes conforme a máquina. `Settings(_env_file=None)` bloqueia o arquivo
# `.env`, mas **não** bloqueia o ambiente — e foi assim que o CI reprovou
# testes que passavam localmente: ele exporta `LLM_SEM_REDE=1`, e todo
# `Settings` construído na suíte passou a nascer com a trava ligada.
VARIAVEIS_DA_APLICACAO = (
    "DATABASE_URL",
    "PERSISTENCIA_ATIVA",
    "DEMO_SOMENTE_LEITURA",
    "LLM_PROVEDOR",
    "LLM_MODELO",
    "LLM_RPM",
    "LLM_RPD",
    "LLM_ARQUIVO_COTAS",
    "LLM_CACHE_ATIVO",
    "LLM_CACHE_DIRETORIO",
    "LLM_SEM_REDE",
    "AUTO_CONSISTENCIA",
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_HOST",
)


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tira do ambiente as variáveis da aplicação, para a suíte inteira.

    Um teste que depende do que está exportado na máquina não é um teste: ele
    passa aqui e reprova no CI, ou o contrário. O `.env` de quem desenvolve tem
    `GEMINI_API_KEY` preenchida; o CI exporta `LLM_SEM_REDE=1`. Nenhum dos dois
    deve chegar a um `Settings` construído dentro de um teste.

    Quem precisa de um valor, passa explicitamente no construtor — que é o que
    a suíte já fazia, e o que só funciona de verdade com esta fixture.
    """
    for variavel in VARIAVEIS_DA_APLICACAO:
        monkeypatch.delenv(variavel, raising=False)

    # `get_settings` é `lru_cache`: sem limpar, a primeira construção do
    # processo — feita durante a coleta, com o ambiente ainda sujo — valeria
    # para a suíte inteira, e tirar a variável do ambiente não mudaria nada.
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def sem_ocr_fora_dos_lentos(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Um teste não marcado como `slow` não pode chamar OCR.

    A trava existe porque a marcação, sozinha, é fácil de esquecer — e o
    esquecimento é invisível na máquina de quem tem tesseract instalado: o teste
    passa, só que rodando OCR, e reprova no CI rápido, que não instala tesseract.
    Foi exatamente o que aconteceu na primeira execução do CI.

    Com esta fixture, esquecer a marcação falha **aqui**, com a mensagem
    dizendo o que fazer.
    """
    if request.node.get_closest_marker("slow") is not None:
        return

    from app.seguranca.detectores import divergencia_ocr

    def recusa(*_: object, **__: object) -> str:
        raise AssertionError(
            f"{request.node.name} chamou OCR sem estar marcado como `slow`. "
            f"Marque-o com @pytest.mark.slow (e com o skipif de tesseract), ou "
            f"passe com_ocr=False se o teste não é sobre a comparação "
            f"texto/imagem. Ver a nota desta fixture."
        )

    monkeypatch.setattr(divergencia_ocr, "texto_da_imagem", recusa)


@pytest.fixture
def fabrica(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@pytest.fixture
def sessao(fabrica: sessionmaker[Session]) -> Iterator[Session]:
    with fabrica() as aberta:
        yield aberta


@pytest.fixture
def cliente(fabrica: sessionmaker[Session]) -> Iterator[TestClient]:
    def sessao_de_teste() -> Iterator[Session]:
        with fabrica() as aberta:
            try:
                yield aberta
                aberta.commit()
            except Exception:
                aberta.rollback()
                raise

    app.dependency_overrides[obtem_sessao] = sessao_de_teste
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key=SecretStr("chave-de-teste"),
        llm_arquivo_cotas=tmp_path / "cotas.json",
        llm_cache_diretorio=tmp_path / "cache",
        auto_consistencia="condicional",
    )
