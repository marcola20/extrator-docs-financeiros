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
from app.config import Settings
from app.main import app
from app.persistencia.modelos import Base


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
