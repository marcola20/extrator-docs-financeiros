"""A entrada da demonstração e o modo somente-leitura.

Duas coisas em teste, e a segunda é a que importa: **quem recusa a escrita é a
API**. Um teste que só conferisse que a tela esconde o botão não diria nada
sobre isso — e é justamente a diferença entre uma demonstração pública e um
formulário aberto para qualquer `curl`.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencias import obtem_sessao
from app.config import Settings, get_settings
from app.demo import CASOS
from app.main import app
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


def _demonstracao(somente_leitura: bool) -> Settings:
    return Settings(
        _env_file=None,
        persistencia_ativa=True,
        demo_somente_leitura=somente_leitura,
        gemini_api_key=SecretStr("nao-usada"),
    )


@pytest.fixture
def cliente_somente_leitura(fabrica: sessionmaker[Session]) -> Iterator[TestClient]:
    """Um cliente sobre uma instância configurada como demonstração pública."""

    def sessao_de_teste() -> Iterator[Session]:
        with fabrica() as aberta:
            try:
                yield aberta
                aberta.commit()
            except Exception:
                aberta.rollback()
                raise

    app.dependency_overrides[obtem_sessao] = sessao_de_teste
    app.dependency_overrides[get_settings] = lambda: _demonstracao(True)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _grava(
    sessao: Session,
    arquivo: Path,
    *,
    rota: Rota = Rota.REVISAO_HUMANA,
    sinais: dict[str, EstadoDoSinal] | None = None,
    achados: int = 0,
) -> Decisao:
    """Uma decisão sobre um arquivo específico — é o caminho que a entrada casa."""
    documento = Documento(
        arquivo=str(arquivo),
        hash_sha256=f"{abs(hash(str(arquivo))):064d}"[:64],
        tipo=TipoDeDocumento.BOLETO,
    )
    sessao.add(documento)
    sessao.flush()

    extracao = Extracao(
        documento_id=documento.id,
        payload={"valor": "1.847,30"},
        prompt="boleto-v2",
        provedor="gabarito",
        modelo="gabarito-sem-rede",
        tokens_entrada=900,
        tokens_saida=120,
    )
    sessao.add(extracao)
    sessao.flush()

    decisao = Decisao(documento_id=documento.id, extracao_id=extracao.id, rota=rota)
    sessao.add(decisao)
    sessao.flush()

    for nome, estado in (sinais or {}).items():
        sessao.add(Sinal(decisao_id=decisao.id, nome=nome, estado=estado, detalhe=nome))
    for indice in range(achados):
        sessao.add(
            Achado(
                decisao_id=decisao.id,
                tipo="texto_quase_invisivel",
                severidade="alta",
                trecho=f"trecho {indice}",
                detalhe="texto na cor do papel",
                pagina=1,
            )
        )
    sessao.commit()
    return decisao


class TestEntrada:
    def test_lista_os_casos_na_ordem_mesmo_sem_nenhum_semeado(self, cliente: TestClient) -> None:
        """Banco vazio não some com os cartões: some com os links."""
        corpo = cliente.get("/demo/casos").json()

        assert [c["chave"] for c in corpo["casos"]] == [caso.chave for caso in CASOS]
        assert all(c["decisao_id"] is None for c in corpo["casos"])

    def test_resolve_o_caso_para_a_decisao_gravada(
        self, cliente: TestClient, sessao: Session
    ) -> None:
        caso = CASOS[0]
        arquivo = caso.arquivo
        assert arquivo is not None
        decisao = _grava(
            sessao,
            arquivo,
            sinais={"aritmetica": EstadoDoSinal.DIVERGENTE, "sanitizacao": EstadoDoSinal.CONFERIDO},
        )

        corpo = cliente.get("/demo/casos").json()
        primeiro = corpo["casos"][0]

        assert primeiro["decisao_id"] == decisao.id
        assert primeiro["rota"] == "revisao_humana"
        assert primeiro["sinais_que_bloqueiam"] == ["aritmetica"]
        assert primeiro["sem_cobertura"] == []

    def test_separa_sem_cobertura_de_reprovado(self, cliente: TestClient, sessao: Session) -> None:
        """A distinção do ADR 009 atravessa até a página de entrada."""
        caso = CASOS[3]
        arquivo = caso.arquivo
        assert arquivo is not None
        _grava(sessao, arquivo, sinais={"aritmetica": EstadoDoSinal.SEM_COBERTURA})

        entrada = next(
            c for c in cliente.get("/demo/casos").json()["casos"] if c["chave"] == caso.chave
        )

        assert entrada["sinais_que_bloqueiam"] == ["aritmetica"]
        assert entrada["sem_cobertura"] == ["aritmetica"]

    def test_conta_os_achados_do_sanitizador(self, cliente: TestClient, sessao: Session) -> None:
        caso = CASOS[2]
        arquivo = caso.arquivo
        assert arquivo is not None
        _grava(sessao, arquivo, achados=3)

        entrada = next(
            c for c in cliente.get("/demo/casos").json()["casos"] if c["chave"] == caso.chave
        )

        assert entrada["achados"] == 3

    def test_o_auto_aprovado_tambem_abre(self, cliente: TestClient, sessao: Session) -> None:
        """Ele não está na fila, e ainda assim tem diagnóstico para mostrar."""
        caso = CASOS[4]
        arquivo = caso.arquivo
        assert arquivo is not None
        decisao = _grava(sessao, arquivo, rota=Rota.AUTO_APROVADO)

        entrada = next(
            c for c in cliente.get("/demo/casos").json()["casos"] if c["chave"] == caso.chave
        )

        assert entrada["rota"] == "auto_aprovado"
        assert entrada["decisao_id"] == decisao.id
        assert cliente.get(f"/revisao/{decisao.id}").status_code == 200


class TestSomenteLeitura:
    def test_a_api_recusa_gravar_correcao(
        self, cliente_somente_leitura: TestClient, sessao: Session
    ) -> None:
        """403, e nada gravado. É a trava; a tela é só a consequência visível."""
        decisao = _grava(sessao, Path("dados/sinteticos/boletos/boleto-001.pdf"))

        resposta = cliente_somente_leitura.post(
            f"/revisao/{decisao.id}/correcoes",
            json={"correcoes": [{"campo": "valor", "valor_corrigido": "1,00"}]},
        )

        assert resposta.status_code == 403
        assert "demonstração" in resposta.json()["detail"]
        assert sessao.scalars(select(Correcao)).all() == []

    def test_recusa_antes_de_procurar_a_decisao(self, cliente_somente_leitura: TestClient) -> None:
        """403 e não 404: a instância não grava, exista o documento ou não.

        Responder 404 aqui contaria ao visitante quais ids existem, e diria
        "tente outro" quando nenhum id vai funcionar.
        """
        resposta = cliente_somente_leitura.post(
            "/revisao/999999/correcoes",
            json={"correcoes": [{"campo": "valor", "valor_corrigido": "1,00"}]},
        )

        assert resposta.status_code == 403

    def test_a_leitura_continua_inteira(
        self, cliente_somente_leitura: TestClient, sessao: Session
    ) -> None:
        """Somente-leitura desliga a escrita, e só ela."""
        decisao = _grava(sessao, Path("dados/sinteticos/boletos/boleto-001.pdf"))

        assert cliente_somente_leitura.get("/revisao/fila").status_code == 200
        assert cliente_somente_leitura.get("/revisao/estatisticas").status_code == 200
        assert cliente_somente_leitura.get(f"/revisao/{decisao.id}").status_code == 200

    def test_o_diagnostico_avisa_a_tela(
        self, cliente_somente_leitura: TestClient, sessao: Session
    ) -> None:
        """O front desabilita o formulário a partir daqui, não de uma env própria."""
        decisao = _grava(sessao, Path("dados/sinteticos/boletos/boleto-001.pdf"))

        corpo = cliente_somente_leitura.get(f"/revisao/{decisao.id}").json()

        assert corpo["somente_leitura"] is True

    def test_a_entrada_avisa_a_tela(self, cliente_somente_leitura: TestClient) -> None:
        assert cliente_somente_leitura.get("/demo/casos").json()["somente_leitura"] is True

    def test_desligado_por_padrao(self, cliente: TestClient, sessao: Session) -> None:
        """Quem roda o projeto localmente grava normalmente."""
        decisao = _grava(sessao, Path("dados/sinteticos/boletos/boleto-001.pdf"))

        resposta = cliente.post(
            f"/revisao/{decisao.id}/correcoes",
            json={"correcoes": [{"campo": "valor", "valor_corrigido": "1,00"}]},
        )

        assert resposta.status_code == 201
        assert cliente.get(f"/revisao/{decisao.id}").json()["somente_leitura"] is False


class TestSaude:
    def test_o_health_diz_o_modo(self, cliente_somente_leitura: TestClient) -> None:
        """Para saber, de fora, se a instância no ar é a demonstração."""
        assert cliente_somente_leitura.get("/health").json()["somente_leitura"] is True
