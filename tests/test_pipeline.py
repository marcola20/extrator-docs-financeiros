"""O pipeline inteiro, de PDF a decisão, sem tocar em rede.

O provedor falso devolve o gabarito do documento, então o que se mede aqui é
o encanamento: se as camadas se conectam, se os sinais recebem a evidência
certa e se a decisão sai coerente. A qualidade da extração é assunto do eval,
que é o único que fala com a API.
"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from app.confianca.politica import Rota, Sinal
from app.config import Settings
from app.extracao.extrator import ExtracaoPorVisaoNaoSuportada
from app.ingestao.documento import CaminhoDeLeitura
from app.ingestao.leitor import ingere
from app.llm.provedor import INSTRUCAO_PADRAO, ResultadoExtracao, UsoDeTokens
from app.pipeline import processa

LIMPO = Path("dados/sinteticos/boletos/boleto-001.pdf")
CORPUS_ADVERSARIAL = Path("dados/sinteticos/boletos_adversariais")


class ProvedorDeGabarito:
    """Devolve os campos do gabarito, como um modelo perfeito devolveria."""

    def __init__(
        self, campos: dict[str, Any], *, sobrescreve: dict[str, str] | None = None
    ) -> None:
        self.campos = campos
        self.sobrescreve = sobrescreve or {}
        self.chamadas = 0

    @property
    def nome(self) -> str:
        return "falso"

    @property
    def modelo(self) -> str:
        return "falso-1"

    def extrai[TSchema: BaseModel](
        self,
        texto: str,
        schema: type[TSchema],
        *,
        instrucao: str = INSTRUCAO_PADRAO,
    ) -> ResultadoExtracao[TSchema]:
        self.chamadas += 1
        carga = {k: ("" if v is None else str(v)) for k, v in self.campos.items()}
        carga.update(self.sobrescreve)
        return ResultadoExtracao(
            dados=schema.model_validate(carga),
            provedor=self.nome,
            modelo=self.modelo,
            uso=UsoDeTokens(entrada=900, saida=120),
            custo_estimado_usd=Decimal("0.000500"),
        )


def _gabarito(pdf: Path) -> dict[str, Any]:
    dados = json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8"))
    return dict(dados.get("campos") or dados["extracao_correta"])


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key=SecretStr("chave-de-teste"),
        llm_arquivo_cotas=tmp_path / "cotas.json",
        llm_cache_diretorio=tmp_path / "cache",
        auto_consistencia="sempre",
    )


class TestDocumentoLimpoEExtracaoFiel:
    def test_auto_aprova(self, settings: Settings) -> None:
        provedor = ProvedorDeGabarito(_gabarito(LIMPO))

        resultado = processa(LIMPO, provedor, settings, provedor_da_segunda=provedor)

        assert resultado.decisao.rota is Rota.AUTO_APROVADO, resultado.decisao.para_revisor()
        assert resultado.ingestao.leitura is CaminhoDeLeitura.TEXTO

    def test_os_quatro_sinais_rodaram(self, settings: Settings) -> None:
        provedor = ProvedorDeGabarito(_gabarito(LIMPO))

        resultado = processa(LIMPO, provedor, settings, provedor_da_segunda=provedor, com_ocr=False)

        assert {v.sinal for v in resultado.decisao.vereditos} == set(Sinal)
        assert resultado.consistencia.executou

    def test_a_extracao_fecha_no_dominio(self, settings: Settings) -> None:
        provedor = ProvedorDeGabarito(_gabarito(LIMPO))

        resultado = processa(LIMPO, provedor, settings, provedor_da_segunda=provedor, com_ocr=False)

        assert resultado.extracao is not None
        assert resultado.extracao.fecha_no_dominio

    def test_custo_e_latencia_ficam_registrados(self, settings: Settings) -> None:
        provedor = ProvedorDeGabarito(_gabarito(LIMPO))

        resultado = processa(LIMPO, provedor, settings, provedor_da_segunda=provedor, com_ocr=False)

        assert resultado.custo_estimado_usd == Decimal("0.001000")
        assert isinstance(resultado.custo_estimado_usd, Decimal)
        assert resultado.latencia_s > 0
        assert resultado.chamadas_ao_modelo == 2


class TestExtracaoErrada:
    def test_valor_alucinado_e_barrado_por_dv_e_grounding(self, settings: Settings) -> None:
        provedor = ProvedorDeGabarito(_gabarito(LIMPO), sobrescreve={"valor": "1,00"})

        resultado = processa(LIMPO, provedor, settings, provedor_da_segunda=provedor, com_ocr=False)

        bloqueadores = {v.sinal for v in resultado.decisao.bloqueadores}
        assert resultado.decisao.rota is Rota.REVISAO_HUMANA
        assert Sinal.DIGITO_VERIFICADOR in bloqueadores
        assert Sinal.GROUNDING in bloqueadores

    def test_divergencia_entre_execucoes_barra(self, settings: Settings) -> None:
        primeiro = ProvedorDeGabarito(_gabarito(LIMPO))
        segundo = ProvedorDeGabarito(
            _gabarito(LIMPO), sobrescreve={"beneficiario_nome": "Outra Empresa"}
        )

        resultado = processa(LIMPO, primeiro, settings, provedor_da_segunda=segundo, com_ocr=False)

        assert resultado.decisao.rota is Rota.REVISAO_HUMANA
        assert "beneficiario_nome" in resultado.decisao.campos_a_revisar


class TestDocumentoAdversarial:
    def test_injecao_visivel_nunca_auto_aprova(self, settings: Settings) -> None:
        """Mesmo com extração perfeita: achado de sanitização basta (Fase 1.2)."""
        gabaritos = sorted(CORPUS_ADVERSARIAL.glob("*.json"))
        alvo = next(
            g
            for g in gabaritos
            if json.loads(g.read_text("utf-8"))["ataque"]["detectavel_pelo_sanitizador"]
        )
        pdf = CORPUS_ADVERSARIAL / json.loads(alvo.read_text("utf-8"))["arquivo_pdf"]
        provedor = ProvedorDeGabarito(_gabarito(pdf))

        resultado = processa(pdf, provedor, settings, provedor_da_segunda=provedor, com_ocr=False)

        assert resultado.decisao.rota is Rota.REVISAO_HUMANA
        assert Sinal.SANITIZACAO in {v.sinal for v in resultado.decisao.bloqueadores}


class TestModoDeConsistencia:
    def test_nunca_dispensa_o_sinal_sem_bloquear(self, tmp_path: Path) -> None:
        settings = Settings(
            _env_file=None,
            gemini_api_key=SecretStr("x"),
            llm_arquivo_cotas=tmp_path / "c.json",
            llm_cache_diretorio=tmp_path / "cache",
            auto_consistencia="nunca",
        )
        provedor = ProvedorDeGabarito(_gabarito(LIMPO))

        resultado = processa(LIMPO, provedor, settings)

        assert resultado.decisao.rota is Rota.AUTO_APROVADO
        assert resultado.consistencia.dispensado
        assert provedor.chamadas == 1

    def test_condicional_nao_gasta_segunda_chamada_quando_tudo_passa(self, tmp_path: Path) -> None:
        settings = Settings(
            _env_file=None,
            gemini_api_key=SecretStr("x"),
            llm_arquivo_cotas=tmp_path / "c.json",
            llm_cache_diretorio=tmp_path / "cache",
            auto_consistencia="condicional",
        )
        provedor = ProvedorDeGabarito(_gabarito(LIMPO))

        resultado = processa(LIMPO, provedor, settings)

        assert provedor.chamadas == 1
        assert "ponto cego" in resultado.consistencia.motivo_de_nao_executar


class TestNuncaChamaRedeSozinho:
    def test_sem_segundo_provedor_o_sinal_falha_em_vez_de_criar_um(
        self, settings: Settings
    ) -> None:
        """O pipeline não constrói provedor.

        Se construísse, um teste que esquecesse de injetar o segundo faria
        chamada de rede de verdade — foi o que aconteceu ao escrever esta
        fase, e a requisição chegou a sair.
        """
        provedor = ProvedorDeGabarito(_gabarito(LIMPO))

        resultado = processa(LIMPO, provedor, settings, com_ocr=False)

        assert not resultado.consistencia.executou
        assert not resultado.consistencia.dispensado
        assert "não foi fornecido" in resultado.consistencia.motivo_de_nao_executar
        assert resultado.decisao.rota is Rota.REVISAO_HUMANA
        assert provedor.chamadas == 1


class TestCaminhoDeVisao:
    def test_documento_sem_camada_de_texto_nao_e_extraido(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        """A ingestão abre o caminho; a extração não o atravessa (ADR 005)."""
        import pypdfium2

        pagina = pypdfium2.PdfDocument(str(LIMPO))[0]
        imagem = pagina.render(scale=150 / 72).to_pil().convert("RGB")
        digitalizado = tmp_path / "digitalizado.pdf"
        imagem.save(digitalizado, "PDF", resolution=150)

        documento = ingere(digitalizado, com_ocr=False)
        assert documento.leitura is CaminhoDeLeitura.VISAO
        assert not documento.sanitizacao_teve_cobertura

        provedor = ProvedorDeGabarito(_gabarito(LIMPO))
        resultado = processa(digitalizado, provedor, settings, com_ocr=False)

        assert resultado.decisao.rota is Rota.REVISAO_HUMANA
        assert resultado.extracao is None
        assert provedor.chamadas == 0

        with pytest.raises(ExtracaoPorVisaoNaoSuportada):
            from app.extracao.extrator import extrai

            extrai(documento, provedor)
