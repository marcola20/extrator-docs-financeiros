"""Do transporte ao domínio, e a aritmética que sobrevive à recusa do domínio."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.dominio.informe import Cobertura, Layout
from app.extracao import extrator_informe as modulo
from app.extracao.extrator import ExtracaoPorVisaoNaoSuportada
from app.extracao.schema_transporte_informe import (
    InformeExtraido,
    LinhaExtraida,
    QuadroExtraido,
    SaldoExtraido,
)
from app.ingestao.documento import CaminhoDeLeitura, DocumentoIngerido
from app.seguranca.sanitizador import ResultadoSanitizacao
from tests.llm.falso import ProvedorFalso

CNPJ = "01.829.356/0001-03"
CPF = "159.748.326-55"


def _bancario(**mudancas: object) -> InformeExtraido:
    """Um informe bancário que fecha em tudo, para os testes desviarem dele."""
    base: dict[str, object] = {
        "layout": "instituicao_financeira",
        "ano_calendario": "2024",
        "exercicio": "2025",
        "fonte_pagadora_cnpj": CNPJ,
        "fonte_pagadora_nome": "Banco Aurora S/A",
        "beneficiario_cpf": CPF,
        "beneficiario_nome": "Maysa da Costa",
        "rendimentos_exclusivos": QuadroExtraido(
            linhas=[
                LinhaExtraida(identificador="CDB", descricao="Certificado", valor="1.000,00"),
                LinhaExtraida(identificador="Fundo DI", descricao="Fundo", valor="500,50"),
            ],
            total_impresso="1.500,50",
        ),
        "saldos": [
            SaldoExtraido(
                especificacao="CDB 8056747",
                saldo_31_12="9.289,25",
                saldo_31_12_anterior="6.771,59",
            )
        ],
    }
    base.update(mudancas)
    return InformeExtraido(**base)


def _comprovante(**mudancas: object) -> InformeExtraido:
    """Um comprovante de fonte pagadora: linhas numeradas, sem total, sem saldo."""
    base: dict[str, object] = {
        "layout": "fonte_pagadora",
        "ano_calendario": "2024",
        "exercicio": "2025",
        "fonte_pagadora_cnpj": CNPJ,
        "fonte_pagadora_nome": "Metalúrgica Vale Verde Ltda",
        "beneficiario_cpf": CPF,
        "beneficiario_nome": "Maysa da Costa",
        "rendimentos_exclusivos": QuadroExtraido(
            linhas=[
                LinhaExtraida(identificador="5.1", descricao="13º salário", valor="4.000,00"),
                LinhaExtraida(identificador="5.2", descricao="IRRF sobre 13º", valor="300,00"),
            ]
        ),
    }
    base.update(mudancas)
    return InformeExtraido(**base)


class TestConversaoAoDominio:
    def test_informe_bancario_bem_lido_fecha(self) -> None:
        informe, erro = modulo.para_dominio(_bancario())

        assert erro is None
        assert informe is not None
        assert informe.layout is Layout.INSTITUICAO_FINANCEIRA
        assert informe.rendimentos_exclusivos.total_impresso == Decimal("1500.50")

    def test_comprovante_bem_lido_fecha_sem_total_e_sem_saldo(self) -> None:
        informe, erro = modulo.para_dominio(_comprovante())

        assert erro is None
        assert informe is not None
        assert informe.rendimentos_exclusivos.total_impresso is None
        assert informe.saldos == ()

    def test_a_formatacao_impressa_nao_atrapalha(self) -> None:
        """`1.000,00` e `1000.00` são o mesmo valor — `app.confianca.campos`."""
        informe, _ = modulo.para_dominio(
            _bancario(
                rendimentos_exclusivos=QuadroExtraido(
                    linhas=[LinhaExtraida(identificador="CDB", valor="1000.00")],
                    total_impresso="R$ 1.000,00",
                )
            )
        )

        assert informe is not None
        assert informe.rendimentos_exclusivos.soma_das_linhas == Decimal("1000.00")


class TestAFalhaNaConversaoEOSinal:
    def test_cnpj_com_dv_errado_nao_fecha(self) -> None:
        informe, erro = modulo.para_dominio(_bancario(fonte_pagadora_cnpj="01.829.356/0001-04"))

        assert informe is None
        assert erro is not None and "CNPJ" in erro

    def test_cpf_com_dv_errado_nao_fecha(self) -> None:
        informe, erro = modulo.para_dominio(_bancario(beneficiario_cpf="159.748.326-56"))

        assert informe is None
        assert erro is not None and "CPF" in erro

    def test_exercicio_que_nao_e_ano_mais_um_nao_fecha(self) -> None:
        informe, erro = modulo.para_dominio(_bancario(exercicio="2026"))

        assert informe is None
        assert erro is not None and "exerc" in erro

    def test_layout_que_o_modelo_inventou_nao_fecha(self) -> None:
        informe, erro = modulo.para_dominio(_bancario(layout="comprovante bancário"))

        assert informe is None
        assert erro is not None and "layout" in erro

    def test_campo_escalar_em_branco_nao_fecha(self) -> None:
        informe, erro = modulo.para_dominio(_bancario(beneficiario_nome=""))

        assert informe is None
        assert erro is not None and "beneficiario_nome" in erro

    def test_linha_sem_identificador_nao_fecha(self) -> None:
        """O identificador é a chave de casamento; sem ela a linha não é medível."""
        informe, erro = modulo.para_dominio(
            _bancario(
                rendimentos_isentos=QuadroExtraido(
                    linhas=[LinhaExtraida(identificador="", valor="10,00")]
                )
            )
        )

        assert informe is None
        assert erro is not None and "identificador" in erro

    def test_valor_de_linha_ilegivel_nao_fecha(self) -> None:
        informe, erro = modulo.para_dominio(
            _bancario(
                rendimentos_isentos=QuadroExtraido(
                    linhas=[LinhaExtraida(identificador="LCI", valor="isento")]
                )
            )
        )

        assert informe is None
        assert erro is not None and "LCI" in erro

    def test_saldo_sem_especificacao_nao_fecha(self) -> None:
        """A especificação é a chave do cruzamento entre anos."""
        informe, erro = modulo.para_dominio(
            _bancario(
                saldos=[
                    SaldoExtraido(especificacao="", saldo_31_12="1,00", saldo_31_12_anterior="0,00")
                ]
            )
        )

        assert informe is None
        assert erro is not None and "especifica" in erro

    def test_comprovante_com_saldo_nao_fecha(self) -> None:
        """Comprovante de fonte pagadora não tem saldo; inventar um seria pior."""
        informe, erro = modulo.para_dominio(
            _comprovante(
                saldos=[
                    SaldoExtraido(
                        especificacao="CDB 1", saldo_31_12="1,00", saldo_31_12_anterior="0,00"
                    )
                ]
            )
        )

        assert informe is None
        assert erro is not None

    def test_o_erro_junta_todos_os_motivos_e_nao_so_o_primeiro(self) -> None:
        """Quem investiga um eval quer a lista, não a primeira parada."""
        _, erro = modulo.para_dominio(_bancario(beneficiario_nome="", fonte_pagadora_nome=""))

        assert erro is not None
        assert "beneficiario_nome" in erro
        assert "fonte_pagadora_nome" in erro


class TestAritmeticaSobreviveARecusaDoDominio:
    """Se ela dependesse do domínio ter fechado, ficaria muda nos dois ataques
    que ela é a única a pegar."""

    def test_total_adulterado_diverge(self) -> None:
        bruto = _bancario(
            rendimentos_exclusivos=QuadroExtraido(
                linhas=[LinhaExtraida(identificador="CDB", valor="1.000,00")],
                total_impresso="2.837,45",
            )
        )

        informe, _ = modulo.para_dominio(bruto)
        conferencias = modulo.confere_quadros(bruto)
        exclusivos = next(c for c in conferencias if c.quadro == "rendimentos_exclusivos")

        assert informe is None, "o domínio recusa, e é isso que torna o teste necessário"
        assert exclusivos.cobertura is Cobertura.DIVERGENTE
        assert exclusivos.soma_das_linhas == Decimal("1000.00")
        assert exclusivos.total_impresso == Decimal("2837.45")

    def test_quadro_duplicado_diverge_mesmo_com_o_dominio_recusando_a_chave(self) -> None:
        """`_identificadores_unicos` recusa a instância; a soma ainda fala."""
        linha = LinhaExtraida(identificador="CDB", valor="1.000,00")
        bruto = _bancario(
            rendimentos_exclusivos=QuadroExtraido(linhas=[linha, linha], total_impresso="1.000,00")
        )

        informe, _ = modulo.para_dominio(bruto)
        exclusivos = next(
            c for c in modulo.confere_quadros(bruto) if c.quadro == "rendimentos_exclusivos"
        )

        assert informe is None
        assert exclusivos.cobertura is Cobertura.DIVERGENTE
        assert exclusivos.soma_das_linhas == Decimal("2000.00")

    def test_linha_injetada_diverge_onde_ha_total(self) -> None:
        bruto = _bancario(
            rendimentos_exclusivos=QuadroExtraido(
                linhas=[
                    LinhaExtraida(identificador="CDB", valor="1.000,00"),
                    LinhaExtraida(identificador="Fundo Imobiliário 8812345", valor="1.837,45"),
                ],
                total_impresso="1.000,00",
            )
        )

        exclusivos = next(
            c for c in modulo.confere_quadros(bruto) if c.quadro == "rendimentos_exclusivos"
        )

        assert exclusivos.cobertura is Cobertura.DIVERGENTE

    def test_linha_ilegivel_nao_derruba_a_conferencia_dos_outros_quadros(self) -> None:
        bruto = _bancario(
            rendimentos_isentos=QuadroExtraido(
                linhas=[LinhaExtraida(identificador="LCI", valor="isento")]
            )
        )

        conferencias = modulo.confere_quadros(bruto)
        exclusivos = next(c for c in conferencias if c.quadro == "rendimentos_exclusivos")

        assert exclusivos.cobertura is Cobertura.CONFERIDO


class TestSemTotalNaoEAprovacao:
    def test_quadro_sem_total_sai_sem_cobertura(self) -> None:
        conferencias = modulo.confere_quadros(_comprovante())
        exclusivos = next(c for c in conferencias if c.quadro == "rendimentos_exclusivos")

        assert exclusivos.cobertura is Cobertura.SEM_TOTAL
        assert not exclusivos.tem_cobertura

    def test_quadro_vazio_com_total_zero_tem_cobertura(self) -> None:
        """Quadro sem lançamento e com total impresso `0,00` foi conferido."""
        conferencias = modulo.confere_quadros(
            _bancario(rendimentos_isentos=QuadroExtraido(total_impresso="0,00"))
        )
        isentos = next(c for c in conferencias if c.quadro == "rendimentos_isentos")

        assert isentos.cobertura is Cobertura.CONFERIDO


class TestSchemaQueVaiAoGemini:
    def test_nao_emite_additional_properties_em_nivel_nenhum(self) -> None:
        """A API recusa esse campo com 400 INVALID_ARGUMENT, e o schema é aninhado."""
        assert "additionalProperties" not in json.dumps(InformeExtraido.model_json_schema())


class TestExtracaoCompleta:
    def _documento(self, texto: str = "texto do informe") -> DocumentoIngerido:
        caminho = Path("informe-001.pdf")
        return DocumentoIngerido(
            caminho=caminho,
            leitura=CaminhoDeLeitura.TEXTO,
            texto=texto,
            sanitizacao=ResultadoSanitizacao(
                documento=caminho, texto=texto, detectores_executados=frozenset({"padroes"})
            ),
        )

    def test_junta_o_bruto_o_dominio_e_a_aritmetica(self) -> None:
        provedor = ProvedorFalso(carga=_bancario().model_dump())

        extracao = modulo.extrai(self._documento(), provedor)

        assert extracao.fecha_no_dominio
        assert extracao.bruto.layout == "instituicao_financeira"
        assert extracao.aritmetica_teve_cobertura
        assert extracao.custo_estimado_usd > 0

    def test_usa_o_prompt_de_informe_e_nao_o_de_boleto(self) -> None:
        provedor = ProvedorFalso(carga=_bancario().model_dump())

        extracao = modulo.extrai(self._documento(), provedor)

        assert extracao.prompt.nome == "informe"
        assert provedor.chamadas[0][1] == extracao.prompt.texto

    def test_comprovante_sem_total_nao_tem_cobertura_aritmetica(self) -> None:
        provedor = ProvedorFalso(carga=_comprovante().model_dump())

        extracao = modulo.extrai(self._documento(), provedor)

        assert extracao.fecha_no_dominio, "o documento é válido"
        assert not extracao.aritmetica_teve_cobertura, "e ainda assim ninguém conferiu soma"
        assert "nenhum quadro tinha total impresso" in extracao.descricao_da_aritmetica()

    def test_documento_sem_camada_de_texto_e_recusado(self) -> None:
        """Mesma razão do boleto: a sanitização da 1.2 não cobre imagem (ADR 005)."""
        caminho = Path("digitalizado.pdf")
        documento = DocumentoIngerido(
            caminho=caminho,
            leitura=CaminhoDeLeitura.VISAO,
            texto="",
            sanitizacao=ResultadoSanitizacao(documento=caminho, texto=""),
        )

        with pytest.raises(ExtracaoPorVisaoNaoSuportada):
            modulo.extrai(documento, ProvedorFalso(carga=_bancario().model_dump()))


class TestLinhasParaAsMetricas:
    def test_devolve_o_que_o_modelo_escreveu_sem_converter(self) -> None:
        linhas = modulo.linhas_por_quadro(_bancario())

        assert linhas["rendimentos_exclusivos"][0]["valor"] == "1.000,00"
        assert linhas["rendimentos_tributaveis"] == []

    def test_traz_os_tres_quadros_sempre(self) -> None:
        assert set(modulo.linhas_por_quadro(InformeExtraido())) == {
            "rendimentos_tributaveis",
            "rendimentos_isentos",
            "rendimentos_exclusivos",
        }
