"""Do resultado do pipeline para as linhas do banco, sem tocar nos pipelines."""

import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.confianca.politica import SINAIS_DO_BOLETO
from app.confianca.politica import Sinal as SinalDaPolitica
from app.config import Settings
from app.persistencia import gravacao
from app.persistencia.modelos import (
    Achado,
    Base,
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

LIMPO = Path("dados/sinteticos/boletos/boleto-001.pdf")
ADVERSARIAL = Path("dados/sinteticos/boletos_adversariais")


@pytest.fixture
def sessao() -> Session:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key=SecretStr("chave-de-teste"),
        llm_arquivo_cotas=tmp_path / "cotas.json",
        llm_cache_diretorio=tmp_path / "cache",
        auto_consistencia="condicional",
    )


com_ocr_de_verdade = pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="tesseract não instalado; sem ele a sanitização nunca auto-aprova",
)


def _grava(
    sessao: Session,
    pdf: Path,
    settings: Settings,
    *,
    sobrescreve: dict[str, str] | None = None,
    com_ocr: bool = False,
) -> Decisao:
    """Processa um documento e grava o resultado, como a API fará."""
    provedor = ProvedorDeGabarito(_gabarito(pdf), sobrescreve=sobrescreve)
    resultado = processa(pdf, provedor, settings, provedor_da_segunda=provedor, com_ocr=com_ocr)
    return gravacao.grava(
        sessao,
        caminho=pdf,
        tipo=TipoDeDocumento.BOLETO,
        ingestao=resultado.ingestao,
        decisao_final=resultado.decisao,
        extracao=resultado.extracao,
        latencia_s=resultado.latencia_s,
    )


class TestOsPipelinesNaoMudaram:
    def test_o_pipeline_nao_importa_persistencia(self) -> None:
        """A restrição da fase, conferida no texto: pipeline não sabe de banco."""
        for modulo in (Path("app/pipeline.py"), Path("app/pipeline_informe.py")):
            fonte = modulo.read_text(encoding="utf-8")

            assert "persistencia" not in fonte, f"{modulo} passou a conhecer o banco"
            assert "sqlalchemy" not in fonte.lower(), f"{modulo} passou a importar SQLAlchemy"

    def test_processar_nao_precisa_de_banco(self, settings: Settings) -> None:
        """O eval processa 56 documentos sem abrir conexão; tem de continuar assim."""
        provedor = ProvedorDeGabarito(_gabarito(LIMPO))

        resultado = processa(LIMPO, provedor, settings, provedor_da_segunda=provedor, com_ocr=False)

        assert resultado.decisao is not None


class TestOsQuatroEstadosChegamAoBanco:
    """A conversão que este módulo existe para não errar."""

    @pytest.mark.slow
    @com_ocr_de_verdade
    def test_sinal_dispensado_nao_vira_sem_cobertura(
        self, sessao: Session, settings: Settings
    ) -> None:
        """`executou=False` significa duas coisas, e só uma delas bloqueia.

        Precisa de OCR: no modo condicional a segunda execução só é dispensada
        quando nenhum outro sinal falhou, e sem a comparação texto/imagem a
        sanitização já falha.
        """
        _grava(sessao, LIMPO, settings, com_ocr=True)
        sessao.commit()

        consistencia = sessao.scalars(
            select(Sinal).where(Sinal.nome == SinalDaPolitica.CONSISTENCIA.value)
        ).one()

        assert consistencia.estado is EstadoDoSinal.DISPENSADO
        assert not consistencia.estado.bloqueia

    def test_sinal_que_reprovou_vira_divergente(self, sessao: Session, settings: Settings) -> None:
        _grava(sessao, LIMPO, settings, sobrescreve={"valor": "99.999,99"})
        sessao.commit()

        dv = sessao.scalars(
            select(Sinal).where(Sinal.nome == SinalDaPolitica.DIGITO_VERIFICADOR.value)
        ).one()

        assert dv.estado is EstadoDoSinal.DIVERGENTE
        assert dv.estado.bloqueia
        assert "não fecha" in dv.detalhe

    def test_sinal_que_aprovou_vira_conferido(self, sessao: Session, settings: Settings) -> None:
        _grava(sessao, LIMPO, settings)
        sessao.commit()

        dv = sessao.scalars(
            select(Sinal).where(Sinal.nome == SinalDaPolitica.DIGITO_VERIFICADOR.value)
        ).one()

        assert dv.estado is EstadoDoSinal.CONFERIDO

    def test_o_detalhe_do_sinal_chega_inteiro(self, sessao: Session, settings: Settings) -> None:
        """É o que diferencia um diagnóstico de um X vermelho na tela."""
        _grava(sessao, LIMPO, settings, sobrescreve={"valor": "99.999,99"})
        sessao.commit()

        detalhes = [s.detalhe for s in sessao.scalars(select(Sinal)).all()]

        assert any(len(d) > 30 for d in detalhes), "detalhes chegaram truncados ou vazios"

    def test_os_quatro_sinais_do_boleto_sao_gravados(
        self, sessao: Session, settings: Settings
    ) -> None:
        """Nenhum veredito se perde no caminho: a tela lista o que o banco tem."""
        _grava(sessao, LIMPO, settings)
        sessao.commit()

        gravados = {
            s.nome for s in sessao.scalars(select(Sinal).where(Sinal.escopo.is_(None))).all()
        }

        assert gravados == {sinal.value for sinal in SINAIS_DO_BOLETO}


class TestPayloadBruto:
    def test_guarda_o_que_o_modelo_escreveu(self, sessao: Session, settings: Settings) -> None:
        _grava(sessao, LIMPO, settings)
        sessao.commit()

        payload = sessao.scalars(select(Extracao)).one().payload

        assert payload["valor"] == str(_gabarito(LIMPO)["valor"])

    def test_custo_e_latencia_ficam_registrados(self, sessao: Session, settings: Settings) -> None:
        _grava(sessao, LIMPO, settings)
        sessao.commit()

        extracao = sessao.scalars(select(Extracao)).one()

        assert isinstance(extracao.custo_usd, Decimal)
        assert extracao.custo_usd > 0
        assert extracao.latencia_s >= 0
        assert extracao.prompt.startswith("boleto-v")


class TestIdentidadePorConteudo:
    def test_reprocessar_nao_duplica_o_documento(self, sessao: Session, settings: Settings) -> None:
        """Duas linhas para o mesmo conteúdo espalhariam as correções."""
        _grava(sessao, LIMPO, settings)
        _grava(sessao, LIMPO, settings)
        sessao.commit()

        assert len(sessao.scalars(select(Documento)).all()) == 1
        assert len(sessao.scalars(select(Decisao)).all()) == 2

    def test_o_hash_e_do_conteudo_e_nao_do_caminho(self, tmp_path: Path) -> None:
        copia = tmp_path / "outro-nome.pdf"
        copia.write_bytes(LIMPO.read_bytes())

        assert gravacao.hash_do_arquivo(copia) == gravacao.hash_do_arquivo(LIMPO)


class TestAchadosDoSanitizador:
    def test_o_trecho_e_a_localizacao_chegam(self, sessao: Session, settings: Settings) -> None:
        """Sem o trecho e onde ele está, o revisor não tem o que conferir."""
        import json

        atacado = next(
            ADVERSARIAL / json.loads(g.read_text("utf-8"))["arquivo_pdf"]
            for g in sorted(ADVERSARIAL.glob("*.json"))
            if json.loads(g.read_text("utf-8"))["ataque"]["detectavel_pelo_sanitizador"]
        )

        _grava(sessao, atacado, settings)
        sessao.commit()

        achados = sessao.scalars(select(Achado)).all()

        assert achados, "documento adversarial detectável não gravou achado nenhum"
        assert all(a.trecho for a in achados)
        assert all(a.pagina >= 1 for a in achados)


class TestDecisaoEFila:
    @pytest.mark.slow
    @com_ocr_de_verdade
    def test_documento_limpo_e_fiel_nao_entra_na_fila(
        self, sessao: Session, settings: Settings
    ) -> None:
        decisao = _grava(sessao, LIMPO, settings, com_ocr=True)
        sessao.commit()

        assert decisao.rota is Rota.AUTO_APROVADO
        assert decisao.revisada_em is None

    def test_documento_com_sinal_reprovado_vai_para_a_fila(
        self, sessao: Session, settings: Settings
    ) -> None:
        decisao = _grava(sessao, LIMPO, settings, sobrescreve={"valor": "99.999,99"})
        sessao.commit()

        assert decisao.rota is Rota.REVISAO_HUMANA


class TestCorrecao:
    def test_grava_o_valor_anterior(self, sessao: Session, settings: Settings) -> None:
        decisao = _grava(sessao, LIMPO, settings, sobrescreve={"valor": "99.999,99"})
        sessao.commit()

        gravacao.grava_correcao(
            sessao,
            decisao=decisao,
            campo="valor",
            valor_anterior="99.999,99",
            valor_corrigido="1.847,30",
            revisor="revisor@exemplo",
        )
        sessao.commit()

        correcao = sessao.scalars(select(Correcao)).one()

        assert correcao.valor_anterior == "99.999,99"
        assert correcao.documento_id == decisao.documento_id


class TestOEvalNaoDependeDeBanco:
    """A restrição da Fase 4, conferida no lugar onde ela quebraria em silêncio.

    O eval processa 56 documentos e é o instrumento de medição do projeto. Se
    ele passasse a exigir Postgres, "rodar o eval" viraria tarefa de
    infraestrutura — e a tarefa apareceria justamente quando alguém quisesse
    conferir um número.

    `TestOsPipelinesNaoMudaram` confere o texto dos dois pipelines; este confere
    o **grafo de imports**, que é mais forte: pega o dia em que alguém importar
    persistência de um módulo que o eval alcança por transitividade.
    """

    def test_importar_o_eval_nao_carrega_sqlalchemy(self) -> None:
        codigo = (
            "import sys; import eval;"
            "print(sorted(m for m in sys.modules "
            "if m.startswith(('sqlalchemy', 'psycopg', 'app.persistencia'))))"
        )
        saida = subprocess.run(
            [sys.executable, "-c", codigo],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[2],
        ).stdout.strip()

        assert saida == "[]", f"o eval passou a arrastar banco junto: {saida}"

    def test_processar_com_persistencia_desligada_e_o_padrao(self) -> None:
        """Desligada por padrão, e é assim que o eval roda."""
        assert Settings(_env_file=None).persistencia_ativa is False
