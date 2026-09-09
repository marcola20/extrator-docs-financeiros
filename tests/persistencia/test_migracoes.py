"""A migração e os modelos descrevem o mesmo schema.

É a divergência que não avisa. Alguém acrescenta uma coluna no modelo, o teste
de mapeamento passa — porque `create_all` monta a tabela a partir do modelo —,
e a migração fica para trás. O sintoma aparece no primeiro deploy, como
`UndefinedColumn` numa consulta que funciona na máquina de quem escreveu.

Aqui as duas são aplicadas a bancos separados e comparadas. Roda em SQLite, e é
por isso que `payload` é uma variante (`JSONB` no Postgres, `JSON` fora): sem
ela, esta conferência exigiria um Postgres de pé e não caberia no CI.
"""

from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect

from app.persistencia.modelos import Base

RAIZ = Path(__file__).resolve().parents[2]


def _configuracao(url: str) -> Config:
    configuracao = Config(str(RAIZ / "alembic.ini"))
    configuracao.set_main_option("script_location", str(RAIZ / "migracoes"))
    configuracao.set_main_option("sqlalchemy.url", url)
    return configuracao


@pytest.fixture
def por_migracao(tmp_path: Path) -> Engine:
    """Um banco construído aplicando as migrações, como em produção."""
    caminho = tmp_path / "migrado.db"
    command.upgrade(_configuracao(f"sqlite:///{caminho}"), "head")
    return create_engine(f"sqlite:///{caminho}", future=True)


@pytest.fixture
def por_modelo(tmp_path: Path) -> Engine:
    """Um banco construído a partir dos modelos."""
    engine = create_engine(f"sqlite:///{tmp_path / 'modelo.db'}", future=True)
    Base.metadata.create_all(engine)
    return engine


def _tabelas(engine: Engine) -> set[str]:
    return {t for t in inspect(engine).get_table_names() if t != "alembic_version"}


def _colunas(engine: Engine, tabela: str) -> dict[str, dict[str, Any]]:
    return {
        c["name"]: {"tipo": str(c["type"]), "nulo": c["nullable"]}
        for c in inspect(engine).get_columns(tabela)
    }


def test_a_migracao_cria_as_mesmas_tabelas_que_os_modelos(
    por_migracao: Engine, por_modelo: Engine
) -> None:
    assert _tabelas(por_migracao) == _tabelas(por_modelo)


def test_as_colunas_batem_tabela_a_tabela(por_migracao: Engine, por_modelo: Engine) -> None:
    """Tipo e nulabilidade, não só o nome: uma coluna que encolheu não avisa."""
    divergencias = {
        tabela: (_colunas(por_migracao, tabela), _colunas(por_modelo, tabela))
        for tabela in sorted(_tabelas(por_modelo))
        if _colunas(por_migracao, tabela) != _colunas(por_modelo, tabela)
    }

    assert not divergencias, f"migração e modelo divergem em: {sorted(divergencias)}"


def test_os_indices_batem(por_migracao: Engine, por_modelo: Engine) -> None:
    """Índice que existe só no modelo vira consulta lenta em produção, calada."""
    for tabela in sorted(_tabelas(por_modelo)):
        da_migracao = {
            (i["name"], tuple(i["column_names"])) for i in inspect(por_migracao).get_indexes(tabela)
        }
        do_modelo = {
            (i["name"], tuple(i["column_names"])) for i in inspect(por_modelo).get_indexes(tabela)
        }

        assert da_migracao == do_modelo, f"índices divergem em {tabela}"


def test_a_migracao_desfaz_o_que_fez(tmp_path: Path) -> None:
    """Sem downgrade testado, a migração é de mão única na hora do problema."""
    configuracao = _configuracao(f"sqlite:///{tmp_path / 'ida-e-volta.db'}")
    command.upgrade(configuracao, "head")
    engine = create_engine(f"sqlite:///{tmp_path / 'ida-e-volta.db'}", future=True)
    assert _tabelas(engine)

    command.downgrade(configuracao, "base")

    assert _tabelas(engine) == set()


def test_ha_exatamente_uma_cabeca(tmp_path: Path) -> None:
    """Duas cabeças é merge de migração esquecido, e `upgrade head` falha nele."""
    from alembic.script import ScriptDirectory

    diretorio = ScriptDirectory.from_config(_configuracao("sqlite://"))

    assert len(diretorio.get_heads()) == 1
