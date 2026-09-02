"""Testes do gerador de boletos sintéticos.

O teste que mais importa aqui é o de ida e volta: tudo que o gerador produz
tem que passar na validação determinística do domínio.
"""

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.dominio.boleto import Boleto
from app.dominio.digito_verificador import valida_linha_digitavel
from app.dominio.linha_digitavel import (
    codigo_barras_de_linha_digitavel,
    fator_vencimento,
    valor_em_centavos,
)
from app.geradores.boleto_sintetico import (
    BANCOS,
    formata_documento,
    formata_moeda,
    gera_lote,
    main,
    renderiza_html,
    salva,
)

HOJE = date(2026, 9, 2)


@pytest.fixture(scope="module")
def lote() -> list[Boleto]:
    return [sintetico.boleto for sintetico in gera_lote(30, semente=2026, hoje=HOJE)]


class TestGeraLote:
    def test_gera_a_quantidade_pedida(self) -> None:
        assert len(gera_lote(7, semente=1, hoje=HOJE)) == 7

    @pytest.mark.parametrize("quantidade", [0, -1])
    def test_recusa_quantidade_nao_positiva(self, quantidade: int) -> None:
        with pytest.raises(ValueError, match="quantidade precisa ser positiva"):
            gera_lote(quantidade)

    def test_mesma_semente_gera_o_mesmo_lote(self) -> None:
        primeiro = gera_lote(5, semente=99, hoje=HOJE)
        segundo = gera_lote(5, semente=99, hoje=HOJE)

        assert primeiro == segundo

    def test_sementes_diferentes_geram_lotes_diferentes(self) -> None:
        primeiro = gera_lote(5, semente=1, hoje=HOJE)
        segundo = gera_lote(5, semente=2, hoje=HOJE)

        assert primeiro != segundo

    def test_usa_bancos_conhecidos(self, lote: list[Boleto]) -> None:
        codigos = {banco.codigo for banco in BANCOS}

        assert {boleto.banco_codigo for boleto in lote} <= codigos

    def test_varia_os_bancos(self, lote: list[Boleto]) -> None:
        assert len({boleto.banco_codigo for boleto in lote}) > 1

    def test_gera_boletos_com_e_sem_pagador(self, lote: list[Boleto]) -> None:
        com_pagador = [boleto for boleto in lote if boleto.pagador_nome is not None]

        assert com_pagador
        assert len(com_pagador) < len(lote)


class TestIdaEVolta:
    def test_toda_linha_gerada_passa_na_validacao(self, lote: list[Boleto]) -> None:
        for boleto in lote:
            resultado = valida_linha_digitavel(boleto.linha_digitavel)
            assert resultado.valido, f"{boleto.linha_digitavel}: {resultado.descricao()}"

    def test_trocar_um_digito_da_linha_reprova(self, lote: list[Boleto]) -> None:
        for boleto in lote:
            for posicao in (0, 9, 15, 32, 46):
                linha = boleto.linha_digitavel
                mutante = (
                    linha[:posicao] + str((int(linha[posicao]) + 1) % 10) + linha[posicao + 1 :]
                )
                assert not valida_linha_digitavel(mutante).valido, (
                    f"{mutante} passou com o dígito {posicao} trocado"
                )

    def test_valor_e_vencimento_batem_com_o_codigo_de_barras(self, lote: list[Boleto]) -> None:
        for boleto in lote:
            codigo = codigo_barras_de_linha_digitavel(boleto.linha_digitavel)

            assert codigo[0:3] == boleto.banco_codigo
            assert codigo[3] == "9"
            assert int(codigo[5:9]) == fator_vencimento(boleto.vencimento)
            assert int(codigo[9:19]) == valor_em_centavos(boleto.valor)

    def test_valor_e_decimal_positivo_com_duas_casas(self, lote: list[Boleto]) -> None:
        for boleto in lote:
            assert isinstance(boleto.valor, Decimal)
            assert boleto.valor > 0
            expoente = boleto.valor.as_tuple().exponent
            assert isinstance(expoente, int) and -expoente <= 2


class TestRenderizacao:
    def test_html_traz_os_campos_principais(self) -> None:
        sintetico = gera_lote(1, semente=5, hoje=HOJE)[0]

        html = renderiza_html(sintetico)

        assert sintetico.boleto.linha_digitavel_formatada in html
        assert sintetico.boleto.beneficiario_nome in html
        assert formata_moeda(sintetico.boleto.valor) in html
        assert "<svg" in html
        assert sintetico.boleto.nosso_numero is not None
        assert sintetico.boleto.nosso_numero in html

    def test_html_escapa_o_nome_do_beneficiario(self) -> None:
        sintetico = gera_lote(1, semente=5, hoje=HOJE)[0]
        malicioso = sintetico.boleto.model_copy(update={"beneficiario_nome": "A & B <script>"})

        html = renderiza_html(replace(sintetico, boleto=malicioso))

        assert "<script>" not in html
        assert "A &amp; B" in html


class TestSalva:
    def test_escreve_pdf_e_gabarito_com_o_mesmo_nome(self, tmp_path: Path) -> None:
        sintetico = gera_lote(1, semente=11, hoje=HOJE)[0]

        caminho_pdf, caminho_json = salva(sintetico, tmp_path, "boleto-001")

        assert caminho_pdf.name == "boleto-001.pdf"
        assert caminho_json.name == "boleto-001.json"
        assert caminho_pdf.read_bytes().startswith(b"%PDF")

    def test_gabarito_volta_a_ser_um_boleto_valido(self, tmp_path: Path) -> None:
        sintetico = gera_lote(1, semente=12, hoje=HOJE)[0]

        _, caminho_json = salva(sintetico, tmp_path, "boleto-001")
        gabarito = json.loads(caminho_json.read_text(encoding="utf-8"))

        assert gabarito["arquivo_pdf"] == "boleto-001.pdf"
        assert gabarito["codigo_barras"] == sintetico.codigo_barras
        assert Boleto.model_validate(gabarito["campos"]) == sintetico.boleto

    def test_cria_o_diretorio_de_destino(self, tmp_path: Path) -> None:
        destino = tmp_path / "nao" / "existe"
        sintetico = gera_lote(1, semente=13, hoje=HOJE)[0]

        caminho_pdf, _ = salva(sintetico, destino, "boleto-001")

        assert caminho_pdf.exists()


class TestCli:
    def test_gera_os_arquivos_pedidos(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        codigo = main(["--quantidade", "2", "--semente", "3", "--saida", str(tmp_path)])

        assert codigo == 0
        assert sorted(caminho.name for caminho in tmp_path.iterdir()) == [
            "boleto-001.json",
            "boleto-001.pdf",
            "boleto-002.json",
            "boleto-002.pdf",
        ]
        assert "2 boletos" in capsys.readouterr().out

    def test_aceita_prefixo(self, tmp_path: Path) -> None:
        main(
            ["--quantidade", "1", "--semente", "3", "--saida", str(tmp_path), "--prefixo", "teste"]
        )

        assert (tmp_path / "teste-001.pdf").exists()


class TestFormatadores:
    @pytest.mark.parametrize(
        ("valor", "texto"),
        [
            (Decimal("0.50"), "0,50"),
            (Decimal("1234.56"), "1.234,56"),
            (Decimal("1000000.00"), "1.000.000,00"),
        ],
    )
    def test_formata_moeda(self, valor: Decimal, texto: str) -> None:
        assert formata_moeda(valor) == texto

    @pytest.mark.parametrize(
        ("documento", "texto"),
        [
            ("11144477735", "111.444.777-35"),
            ("11222333000181", "11.222.333/0001-81"),
            (None, ""),
            ("123", "123"),
        ],
    )
    def test_formata_documento(self, documento: str | None, texto: str) -> None:
        assert formata_documento(documento) == texto
