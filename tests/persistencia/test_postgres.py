"""A verificação que o SQLite não faz: contra um Postgres de verdade.

Existe porque a suíte roda em SQLite, e **duas descrições podem concordar em
estar erradas**: `test_migracoes.py` compara migração e modelos entre si, e os
dois estavam igualmente sem os CHECK dos enums até alguém olhar um banco real
(ver ADR 010).

Pula quando não há Postgres de pé, e pular é o comportamento certo — a Fase 4
decidiu que persistência é opcional, e uma suíte que exigisse o serviço
contradiria a decisão.

**Pula também quando `PYTEST_POSTGRES` não está ligado, e isso não é excesso de
zelo.** O teardown apaga as seis tabelas, porque um teste que deixa lixo no
banco de desenvolvimento é pior que nenhum teste. Se bastasse haver um Postgres
alcançável, um `uv run pytest` comum — a suíte completa, que alguém roda antes
de commitar — apagaria os dados de quem estivesse usando a fila de revisão, sem
ter pedido nada. Apagar dado é o tipo de coisa que se faz sob pedido explícito.

    docker compose up -d
    PYTEST_POSTGRES=1 uv run pytest -m postgres
"""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencias import obtem_sessao
from app.avaliacao.exporta_realimentacao import casos_revisados
from app.config import Settings
from app.main import app
from app.persistencia import gravacao
from app.persistencia.modelos import (
    Achado,
    Correcao,
    Decisao,
    Documento,
    EstadoDoSinal,
    Extracao,
    Rota,
    Sinal,
    TipoDeDocumento,
)
from app.pipeline import processa
from tests.test_pipeline import ProvedorDeGabarito, _gabarito

pytestmark = pytest.mark.postgres

CORPUS = Path("dados/sinteticos/boletos")
LIMPO = CORPUS / "boleto-001.pdf"
ADVERSARIAIS = Path("dados/sinteticos/boletos_adversariais")

URL = "postgresql+psycopg://extrator:extrator@localhost:5432/extrator"
TABELAS = ("sinal", "achado", "correcao", "decisao", "extracao", "documento")


def _engine_ou_pula() -> Engine:
    if os.environ.get("PYTEST_POSTGRES", "").strip() not in ("1", "true", "sim"):
        pytest.skip(
            "PYTEST_POSTGRES não está ligado. Estes testes APAGAM as tabelas ao "
            "terminar; ligue a variável para autorizar isso no banco de "
            "DATABASE_URL: PYTEST_POSTGRES=1 uv run pytest -m postgres"
        )

    engine = create_engine(URL, pool_pre_ping=True)
    try:
        with engine.connect() as conexao:
            conexao.execute(text("select 1"))
    except OperationalError:
        pytest.skip("nenhum Postgres em localhost:5432; `docker compose up -d` para rodar")
    return engine


@pytest.fixture(scope="module")
def engine() -> Engine:
    return _engine_ou_pula()


@pytest.fixture
def sessao(engine: Engine) -> Iterator[Session]:
    """Uma sessão limpa, que desfaz o que o teste criou.

    O banco é o de desenvolvimento de quem roda; deixar lixo nele seria pior que
    não testar.
    """
    fabrica = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with fabrica() as aberta:
        yield aberta
    with engine.begin() as conexao:
        for tabela in TABELAS:
            conexao.execute(text(f"delete from {tabela}"))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key=SecretStr("chave-de-teste"),
        llm_arquivo_cotas=tmp_path / "cotas.json",
        llm_cache_diretorio=tmp_path / "cache",
        auto_consistencia="condicional",
        persistencia_ativa=True,
    )


@pytest.fixture
def cliente(engine: Engine) -> Iterator[TestClient]:
    fabrica = sessionmaker(bind=engine, expire_on_commit=False, future=True)

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


def _um_adversarial_detectavel() -> Path:
    """Um documento cujo ataque o sanitizador pega sem precisar de OCR.

    `padroes` é o **detector**; `padrao_de_injecao` é o tipo de achado que ele
    produz. Procurar pelo segundo aqui faz o teste pular em silêncio — foi o que
    aconteceu na primeira execução, e um teste que pula não verifica nada.
    """
    for gabarito in sorted(ADVERSARIAIS.glob("*.json")):
        dados = json.loads(gabarito.read_text(encoding="utf-8"))
        if "padroes" in dados["ataque"]["detectores_esperados"]:
            return ADVERSARIAIS / str(dados["arquivo_pdf"])
    pytest.skip("corpus adversarial sem ataque detectável por padrão")


def _grava(
    sessao: Session,
    pdf: Path,
    settings: Settings,
    *,
    sobrescreve: dict[str, str] | None = None,
) -> Decisao:
    provedor = ProvedorDeGabarito(_gabarito(pdf), sobrescreve=sobrescreve)
    resultado = processa(pdf, provedor, settings, provedor_da_segunda=provedor, com_ocr=False)
    decisao = gravacao.grava(
        sessao,
        caminho=pdf,
        tipo=TipoDeDocumento.BOLETO,
        ingestao=resultado.ingestao,
        decisao_final=resultado.decisao,
        extracao=resultado.extracao,
        latencia_s=resultado.latencia_s,
    )
    sessao.commit()
    return decisao


class TestOSchemaEOQueOsModelosDizem:
    """O que o SQLite não podia provar: os tipos são mesmo os do Postgres."""

    def test_payload_e_jsonb_de_verdade(self, engine: Engine) -> None:
        tipos = {c["name"]: str(c["type"]) for c in inspect(engine).get_columns("extracao")}

        assert tipos["payload"] == "JSONB"

    def test_as_datas_sao_timestamptz(self, engine: Engine) -> None:
        """Pelo `information_schema`, que é o que o banco declara.

        O `str()` do tipo do inspector diz só `TIMESTAMP` nos dois casos — o
        fuso é uma propriedade dele, não parte do nome —, e assim a asserção
        passaria com `timestamp without time zone`, que é justamente o defeito
        que ela existe para pegar.
        """
        with engine.connect() as conexao:
            declarados = {
                f"{tabela}.{coluna}": tipo
                for tabela, coluna, tipo in conexao.execute(
                    text(
                        "select table_name, column_name, data_type "
                        "from information_schema.columns "
                        "where table_schema = 'public' and data_type like 'timestamp%'"
                    )
                ).all()
            }

        assert declarados
        for onde, tipo in declarados.items():
            assert tipo == "timestamp with time zone", f"{onde} é {tipo}"

    def test_dinheiro_e_numeric_e_nao_ponto_flutuante(self, engine: Engine) -> None:
        tipos = {c["name"]: str(c["type"]) for c in inspect(engine).get_columns("extracao")}

        assert tipos["custo_usd"].startswith("NUMERIC")

    def test_nao_existe_tipo_enum_nativo(self, engine: Engine) -> None:
        """`ALTER TYPE` não roda dentro de transação; a restrição é CHECK."""
        with engine.connect() as conexao:
            nativos = (
                conexao.execute(text("select typname from pg_type where typtype = 'e'"))
                .scalars()
                .all()
            )

        assert nativos == []

    def test_os_enums_tem_check_no_banco(self, engine: Engine) -> None:
        """Faltavam, e só apareceu ao olhar um Postgres. Ver ADR 010."""
        with engine.connect() as conexao:
            restricoes: dict[str, str] = {
                nome: definicao
                for nome, definicao in conexao.execute(
                    text(
                        "select con.conname, pg_get_constraintdef(con.oid) "
                        "from pg_constraint con join pg_class rel on rel.oid = con.conrelid "
                        "where con.contype = 'c'"
                    )
                ).all()
            }

        assert "ck_estadodosinal" in restricoes
        for estado in EstadoDoSinal:
            assert f"'{estado.value}'" in restricoes["ck_estadodosinal"]

    def test_o_banco_recusa_um_quinto_estado(self, engine: Engine, sessao: Session) -> None:
        """A garantia de conjunto fechado tem de ser do banco, não só do ORM."""
        documento = Documento(arquivo="x.pdf", hash_sha256="a" * 64, tipo=TipoDeDocumento.BOLETO)
        sessao.add(documento)
        sessao.flush()
        decisao = Decisao(documento_id=documento.id, rota=Rota.REVISAO_HUMANA)
        sessao.add(decisao)
        sessao.commit()

        with pytest.raises(IntegrityError, match="ck_estadodosinal"):
            sessao.execute(
                text(
                    "insert into sinal (decisao_id, nome, estado, detalhe) "
                    f"values ({decisao.id}, 'x', 'talvez', '')"
                )
            )
            sessao.commit()
        sessao.rollback()


class TestGravaOProcessamentoInteiro:
    def test_documento_extracao_sinais_e_decisao(self, sessao: Session, settings: Settings) -> None:
        decisao = _grava(sessao, LIMPO, settings, sobrescreve={"valor": "99.999,99"})

        assert sessao.scalars(select(Documento)).one().hash_sha256
        assert sessao.scalars(select(Extracao)).one().payload
        assert len(sessao.scalars(select(Sinal)).all()) >= 4
        assert decisao.rota is Rota.REVISAO_HUMANA

    def test_os_achados_do_sanitizador(self, sessao: Session, settings: Settings) -> None:
        """O trecho e a localização, que é o que o revisor abre para comparar."""
        _grava(sessao, _um_adversarial_detectavel(), settings)

        achados = sessao.scalars(select(Achado)).all()

        assert achados
        assert all(a.trecho and a.pagina >= 1 for a in achados)

    def test_reprocessar_nao_duplica_o_documento(self, sessao: Session, settings: Settings) -> None:
        _grava(sessao, LIMPO, settings)
        _grava(sessao, LIMPO, settings)

        assert len(sessao.scalars(select(Documento)).all()) == 1
        assert len(sessao.scalars(select(Decisao)).all()) == 2


class TestOsTiposVoltamCertos:
    """Os dois defeitos que os testes pegaram em SQLite, conferidos no Postgres."""

    def test_o_estado_volta_como_enum_e_nao_como_str(
        self, sessao: Session, settings: Settings
    ) -> None:
        """`mapped_column(String)` gravava certo e lia errado: voltava `str`,
        e `estado.bloqueia` levantaria `AttributeError` no consumidor."""
        _grava(sessao, LIMPO, settings, sobrescreve={"valor": "99.999,99"})
        sessao.expire_all()

        for sinal in sessao.scalars(select(Sinal)):
            assert isinstance(sinal.estado, EstadoDoSinal), type(sinal.estado)
            assert isinstance(sinal.estado.bloqueia, bool)

    def test_a_rota_e_o_tipo_tambem(self, sessao: Session, settings: Settings) -> None:
        _grava(sessao, LIMPO, settings)
        sessao.expire_all()

        assert isinstance(sessao.scalars(select(Decisao)).one().rota, Rota)
        assert isinstance(sessao.scalars(select(Documento)).one().tipo, TipoDeDocumento)

    def test_as_datas_voltam_com_fuso(self, sessao: Session, settings: Settings) -> None:
        """Sem fuso, comparar com `datetime.now(UTC)` levanta `TypeError`."""
        _grava(sessao, LIMPO, settings)
        sessao.expire_all()

        ingerido = sessao.scalars(select(Documento)).one().ingerido_em

        assert ingerido.tzinfo is not None
        assert ingerido <= datetime.now(UTC)

    def test_o_custo_volta_como_decimal(self, sessao: Session, settings: Settings) -> None:
        _grava(sessao, LIMPO, settings)
        sessao.expire_all()

        custo = sessao.scalars(select(Extracao)).one().custo_usd

        assert isinstance(custo, Decimal)
        assert custo > 0

    def test_o_payload_atravessa_o_jsonb_sem_converter(
        self, sessao: Session, settings: Settings
    ) -> None:
        """A pergunta "o modelo escreveu 1.847,30 ou 1847.30?" só tem resposta aqui."""
        _grava(sessao, LIMPO, settings, sobrescreve={"valor": "99.999,99"})
        sessao.expire_all()

        assert sessao.scalars(select(Extracao)).one().payload["valor"] == "99.999,99"


class TestCorrecaoPelaApi:
    def test_persiste_e_o_exportador_a_registra(
        self, cliente: TestClient, sessao: Session, settings: Settings
    ) -> None:
        decisao = _grava(sessao, LIMPO, settings, sobrescreve={"valor": "99.999,99"})

        resposta = cliente.post(
            f"/revisao/{decisao.id}/correcoes",
            json={
                "correcoes": [
                    {
                        "campo": "valor",
                        "valor_anterior": "99.999,99",
                        "valor_corrigido": "1.847,30",
                    }
                ],
                "revisor": "ensaio@postgres",
            },
        )

        assert resposta.status_code == 201

        sessao.expire_all()
        correcao = sessao.scalars(select(Correcao)).one()
        assert correcao.valor_corrigido == "1.847,30"
        assert correcao.corrigido_em.tzinfo is not None

        casos = casos_revisados(sessao)
        assert len(casos) == 1
        assert casos[0].campos["valor"] == "1.847,30"
        assert casos[0].procedencia.origem == "correcao_humana"
        assert casos[0].procedencia.revisor == "ensaio@postgres"
        assert casos[0].procedencia.campos_corrigidos == ("valor",)

    def test_o_item_sai_da_fila_depois_de_fechado(
        self, cliente: TestClient, sessao: Session, settings: Settings
    ) -> None:
        decisao = _grava(sessao, LIMPO, settings, sobrescreve={"valor": "99.999,99"})
        assert cliente.get("/revisao/fila").json()["total"] == 1

        cliente.post(
            f"/revisao/{decisao.id}/correcoes",
            json={"correcoes": [{"campo": "valor", "valor_corrigido": "1.847,30"}]},
        )

        assert cliente.get("/revisao/fila").json()["total"] == 0

    def test_o_diagnostico_traz_os_quatro_estados(
        self, cliente: TestClient, sessao: Session, settings: Settings
    ) -> None:
        decisao = _grava(sessao, LIMPO, settings, sobrescreve={"valor": "99.999,99"})

        sinais = cliente.get(f"/revisao/{decisao.id}").json()["sinais"]

        estados = {s["estado"] for s in sinais}
        assert estados <= {e.value for e in EstadoDoSinal}
        assert any(s["bloqueia"] for s in sinais)
