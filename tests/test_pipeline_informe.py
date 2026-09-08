"""O pipeline do informe, de PDF a decisão, sem tocar em rede.

O provedor falso devolve o gabarito do documento, como um modelo perfeito
devolveria. O que se mede aqui é o encanamento — se as camadas se conectam,
se o cruzamento entre anos recebe os dois documentos, e se a decisão sai
coerente. A qualidade da extração é assunto do eval.
"""

import json
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from app.confianca.normalizacao import digitos, texto_comparavel
from app.confianca.politica import Rota, Sinal
from app.config import Settings
from app.llm.provedor import INSTRUCAO_PADRAO, ResultadoExtracao, UsoDeTokens
from app.pipeline_informe import decide_par, le, processa, processa_par

CORPUS = Path("dados/sinteticos/informes")

# par-001: informe bancário, que tem total impresso e tabela de saldos.
BANCARIO_ANTERIOR = CORPUS / "informe-001.pdf"
BANCARIO_DO_ANO = CORPUS / "informe-002.pdf"

# par-002: comprovante de fonte pagadora, sem total e sem saldo. Ver ADR 007.
COMPROVANTE_ANTERIOR = CORPUS / "informe-003.pdf"
COMPROVANTE_DO_ANO = CORPUS / "informe-004.pdf"


def _gabarito(pdf: Path) -> dict[str, Any]:
    dados: dict[str, Any] = json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8"))
    return dict(dados["campos"])


def _como_transporte(campos: dict[str, Any]) -> dict[str, Any]:
    """O gabarito do domínio na forma do transporte: tudo texto."""
    carga: dict[str, Any] = {
        chave: str(campos[chave])
        for chave in (
            "layout",
            "ano_calendario",
            "exercicio",
            "fonte_pagadora_cnpj",
            "fonte_pagadora_nome",
            "beneficiario_cpf",
            "beneficiario_nome",
        )
    }
    for nome in ("rendimentos_tributaveis", "rendimentos_isentos", "rendimentos_exclusivos"):
        quadro = campos[nome]
        carga[nome] = {
            "linhas": [
                {
                    "identificador": linha["identificador"],
                    "descricao": linha["descricao"],
                    "valor": str(linha["valor"]),
                }
                for linha in quadro["linhas"]
            ],
            "total_impresso": (
                "" if quadro["total_impresso"] is None else str(quadro["total_impresso"])
            ),
        }
    carga["saldos"] = [
        {
            "especificacao": saldo["especificacao"],
            "saldo_31_12": str(saldo["saldo_31_12"]),
            "saldo_31_12_anterior": str(saldo["saldo_31_12_anterior"]),
        }
        for saldo in campos["saldos"]
    ]
    return carga


class ProvedorDeGabarito:
    """Devolve o gabarito do PDF pedido, escolhido pelo texto que chega."""

    def __init__(self, *, sobrescreve: dict[Path, dict[str, Any]] | None = None) -> None:
        self.sobrescreve = sobrescreve or {}
        self.chamadas = 0
        self._corpus = [
            (pdf, _gabarito(pdf))
            for pdf in (
                BANCARIO_ANTERIOR,
                BANCARIO_DO_ANO,
                COMPROVANTE_ANTERIOR,
                COMPROVANTE_DO_ANO,
            )
        ]

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
        pdf, campos = self._reconhece(texto)
        carga = _como_transporte(campos)
        for chave, valor in self.sobrescreve.get(pdf, {}).items():
            carga[chave] = valor
        return ResultadoExtracao(
            dados=schema.model_validate(carga),
            provedor=self.nome,
            modelo=self.modelo,
            uso=UsoDeTokens(entrada=1800, saida=400),
            custo_estimado_usd=Decimal("0.000500"),
        )

    def _reconhece(self, texto: str) -> tuple[Path, dict[str, Any]]:
        """Qual documento do corpus é este texto.

        Casa por CPF **e exercício**: os dois documentos de um par têm o mesmo
        titular, e o ano-calendário de um aparece impresso no outro, na coluna
        de saldo de 31/12 do ano anterior. O exercício só aparece no cabeçalho,
        e é o que separa os dois.
        """
        comparavel = texto_comparavel(texto)
        do_texto = digitos(texto)
        for pdf, campos in self._corpus:
            exercicio = str(campos["exercicio"])
            no_cabecalho = (
                f"exercicio de {exercicio}" in comparavel or f"exercicio {exercicio}" in comparavel
            )
            if campos["beneficiario_cpf"] in do_texto and no_cabecalho:
                return pdf, campos
        raise AssertionError(f"texto não corresponde a nenhum informe do corpus: {texto[:120]!r}")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key=SecretStr("chave-de-teste"),
        llm_arquivo_cotas=tmp_path / "cotas.json",
        llm_cache_diretorio=tmp_path / "cache",
        auto_consistencia="condicional",
    )


def _par(
    settings: Settings,
    provedor: ProvedorDeGabarito,
    a: Path,
    b: Path,
    *,
    com_ocr: bool = False,
) -> Any:
    return processa_par(a, b, provedor, settings, provedor_da_segunda=provedor, com_ocr=com_ocr)


# A auto-aprovação exige que a comparação texto/imagem tenha rodado: sem ela a
# política da Fase 1.2 já bloqueia, porque texto invisível não foi procurado.
# Os testes que afirmam a **rota** precisam de OCR de verdade, e por isso são
# lentos; os que afirmam um veredito específico rodam sem.
com_ocr_de_verdade = pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="tesseract não instalado; sem ele a sanitização nunca auto-aprova",
)


class TestInformeBancarioComPar:
    @pytest.mark.slow
    @com_ocr_de_verdade
    def test_e_auto_aprovado_quando_tudo_confere(self, settings: Settings) -> None:
        anterior, do_ano = _par(
            settings, ProvedorDeGabarito(), BANCARIO_ANTERIOR, BANCARIO_DO_ANO, com_ocr=True
        )

        assert do_ano.decisao.rota is Rota.AUTO_APROVADO, do_ano.decisao.para_revisor()
        assert anterior.decisao.rota is Rota.AUTO_APROVADO

    def test_a_cobertura_e_real_e_nao_por_omissao(self, settings: Settings) -> None:
        _, do_ano = _par(settings, ProvedorDeGabarito(), BANCARIO_ANTERIOR, BANCARIO_DO_ANO)

        assert do_ano.teve_cobertura_real
        assert do_ano.cruzamento is not None and do_ano.cruzamento.contas_conferidas

    def test_o_cruzamento_recebe_os_dois_documentos(self, settings: Settings) -> None:
        _, do_ano = _par(settings, ProvedorDeGabarito(), BANCARIO_ANTERIOR, BANCARIO_DO_ANO)
        veredito = next(v for v in do_ano.decisao.vereditos if v.sinal is Sinal.CRUZAMENTO)

        assert veredito.executou and veredito.aprovou

    @pytest.mark.slow
    @com_ocr_de_verdade
    def test_a_ordem_dos_argumentos_nao_importa(self, settings: Settings) -> None:
        """Quem é o ano e quem é o anterior sai do `ano_calendario` extraído."""
        invertido, _ = _par(
            settings, ProvedorDeGabarito(), BANCARIO_DO_ANO, BANCARIO_ANTERIOR, com_ocr=True
        )

        assert invertido.decisao.rota is Rota.AUTO_APROVADO

    @pytest.mark.slow
    @com_ocr_de_verdade
    def test_cada_documento_e_extraido_uma_vez_so(self, settings: Settings) -> None:
        """Custo e latência são por documento; extrair o par de novo dobraria a cota."""
        provedor = ProvedorDeGabarito()

        _par(settings, provedor, BANCARIO_ANTERIOR, BANCARIO_DO_ANO, com_ocr=True)

        assert provedor.chamadas == 2

    @pytest.mark.slow
    @com_ocr_de_verdade
    def test_custo_e_latencia_nao_contam_o_par_junto(self, settings: Settings) -> None:
        anterior, do_ano = _par(
            settings, ProvedorDeGabarito(), BANCARIO_ANTERIOR, BANCARIO_DO_ANO, com_ocr=True
        )

        assert do_ano.chamadas_ao_modelo == 1
        assert anterior.chamadas_ao_modelo == 1
        assert do_ano.custo_estimado_usd == Decimal("0.000500")


class TestComprovanteDeFontePagadora:
    """O layout pobre em sinal do ADR 007, e a consequência que o ADR 009 assume."""

    def test_nunca_e_auto_aprovado_mesmo_lido_perfeitamente(self, settings: Settings) -> None:
        anterior, do_ano = _par(
            settings, ProvedorDeGabarito(), COMPROVANTE_ANTERIOR, COMPROVANTE_DO_ANO
        )

        assert do_ano.decisao.rota is Rota.REVISAO_HUMANA
        assert anterior.decisao.rota is Rota.REVISAO_HUMANA

    @pytest.mark.slow
    @com_ocr_de_verdade
    def test_e_vai_a_revisao_por_falta_de_cobertura_e_nao_por_reprovacao(
        self, settings: Settings
    ) -> None:
        """A distinção que o relatório precisa manter separada."""
        _, do_ano = _par(
            settings, ProvedorDeGabarito(), COMPROVANTE_ANTERIOR, COMPROVANTE_DO_ANO, com_ocr=True
        )

        assert do_ano.decisao.so_falta_de_cobertura, do_ano.decisao.para_revisor()
        assert not do_ano.teve_cobertura_real
        assert do_ano.extracao is not None and do_ano.extracao.fecha_no_dominio

    def test_o_dominio_fecha_e_o_relatorio_diz_isso(self, settings: Settings) -> None:
        """Não fechar e não ter sido conferido são coisas diferentes."""
        _, do_ano = _par(settings, ProvedorDeGabarito(), COMPROVANTE_ANTERIOR, COMPROVANTE_DO_ANO)
        dominio = next(v for v in do_ano.decisao.vereditos if v.sinal is Sinal.DOMINIO)

        assert dominio.aprovou and not dominio.bloqueia


class TestDocumentoSemPar:
    def test_nao_e_auto_aprovavel(self, settings: Settings) -> None:
        provedor = ProvedorDeGabarito()

        resultado = processa(
            BANCARIO_DO_ANO, provedor, settings, provedor_da_segunda=provedor, com_ocr=False
        )

        assert resultado.decisao.rota is Rota.REVISAO_HUMANA
        assert resultado.par is None

    def test_o_cruzamento_diz_que_nao_rodou_e_por_que(self, settings: Settings) -> None:
        provedor = ProvedorDeGabarito()

        resultado = processa(
            BANCARIO_DO_ANO, provedor, settings, provedor_da_segunda=provedor, com_ocr=False
        )
        veredito = next(v for v in resultado.decisao.vereditos if v.sinal is Sinal.CRUZAMENTO)

        assert not veredito.executou
        assert "par" in veredito.detalhe


class TestSaldoAdulteradoEntreAnos:
    """O ataque que só o cruzamento vê: a página é impecável e o par a desmente."""

    def test_saldo_anterior_trocado_e_barrado(self, settings: Settings) -> None:
        campos = _gabarito(BANCARIO_DO_ANO)
        saldos = _como_transporte(campos)["saldos"]
        assert saldos, "o par-001 é bancário e tem saldos"
        adulterado = [dict(s) for s in saldos]
        adulterado[0]["saldo_31_12_anterior"] = str(
            Decimal(adulterado[0]["saldo_31_12_anterior"]) + Decimal("1837.45")
        )

        provedor = ProvedorDeGabarito(sobrescreve={BANCARIO_DO_ANO: {"saldos": adulterado}})
        _, do_ano = _par(settings, provedor, BANCARIO_ANTERIOR, BANCARIO_DO_ANO)

        cruzamento = next(v for v in do_ano.decisao.vereditos if v.sinal is Sinal.CRUZAMENTO)

        assert cruzamento.executou and not cruzamento.aprovou
        assert do_ano.decisao.rota is Rota.REVISAO_HUMANA
        assert not do_ano.decisao.so_falta_de_cobertura, "isto é reprovação, não falta de cobertura"

    def test_o_par_intocado_tambem_vai_a_revisao(self, settings: Settings) -> None:
        """Os dois documentos afirmam a mesma grandeza; um desmente o outro."""
        campos = _gabarito(BANCARIO_DO_ANO)
        adulterado = [dict(s) for s in _como_transporte(campos)["saldos"]]
        adulterado[0]["saldo_31_12_anterior"] = "1.00"

        provedor = ProvedorDeGabarito(sobrescreve={BANCARIO_DO_ANO: {"saldos": adulterado}})
        anterior, _ = _par(settings, provedor, BANCARIO_ANTERIOR, BANCARIO_DO_ANO)

        assert anterior.decisao.rota is Rota.REVISAO_HUMANA


class TestUmDosDoisNaoFecha:
    def test_o_cruzamento_fica_sem_cobertura_e_diz_qual_documento(self, settings: Settings) -> None:
        provedor = ProvedorDeGabarito(
            sobrescreve={BANCARIO_DO_ANO: {"fonte_pagadora_cnpj": "01.829.356/0001-04"}}
        )

        anterior, do_ano = _par(settings, provedor, BANCARIO_ANTERIOR, BANCARIO_DO_ANO)
        veredito = next(v for v in anterior.decisao.vereditos if v.sinal is Sinal.CRUZAMENTO)

        assert not veredito.executou
        assert BANCARIO_DO_ANO.name in veredito.detalhe
        assert do_ano.decisao.rota is Rota.REVISAO_HUMANA


class TestSegundaExecucao:
    @pytest.mark.slow
    @com_ocr_de_verdade
    def test_condicional_nao_gasta_chamada_quando_nada_reprova(self, settings: Settings) -> None:
        provedor = ProvedorDeGabarito()

        _par(settings, provedor, BANCARIO_ANTERIOR, BANCARIO_DO_ANO, com_ocr=True)

        assert provedor.chamadas == 2

    @pytest.mark.slow
    @com_ocr_de_verdade
    def test_quadro_sem_total_nao_dispara_a_segunda(self, settings: Settings) -> None:
        """Metade do corpus é comprovante; dobrar a cota neles não mudaria decisão."""
        provedor = ProvedorDeGabarito()

        _par(settings, provedor, COMPROVANTE_ANTERIOR, COMPROVANTE_DO_ANO, com_ocr=True)

        assert provedor.chamadas == 2

    def test_sempre_roda_a_segunda_em_todos(self, tmp_path: Path) -> None:
        configuracao = Settings(
            _env_file=None,
            gemini_api_key=SecretStr("chave-de-teste"),
            llm_arquivo_cotas=tmp_path / "cotas.json",
            llm_cache_diretorio=tmp_path / "cache",
            auto_consistencia="sempre",
        )
        provedor = ProvedorDeGabarito()

        _par(configuracao, provedor, BANCARIO_ANTERIOR, BANCARIO_DO_ANO)

        assert provedor.chamadas == 4

    def test_sem_segundo_provedor_o_sinal_falha_em_vez_de_criar_um(self, tmp_path: Path) -> None:
        configuracao = Settings(
            _env_file=None,
            gemini_api_key=SecretStr("chave-de-teste"),
            llm_arquivo_cotas=tmp_path / "cotas.json",
            llm_cache_diretorio=tmp_path / "cache",
            auto_consistencia="sempre",
        )

        leitura = le(BANCARIO_DO_ANO, ProvedorDeGabarito(), configuracao, com_ocr=False)

        assert not leitura.consistencia.executou
        assert not leitura.consistencia.dispensado


class TestDecisaoPorParEPura:
    def test_decide_par_nao_chama_o_modelo(self, settings: Settings) -> None:
        provedor = ProvedorDeGabarito()
        primeira = le(BANCARIO_ANTERIOR, provedor, settings, com_ocr=False)
        segunda = le(BANCARIO_DO_ANO, provedor, settings, com_ocr=False)
        antes = provedor.chamadas

        decide_par(primeira, segunda)

        assert provedor.chamadas == antes
