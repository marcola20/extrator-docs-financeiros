"""Gerador adversarial: o gabarito precisa ser coerente com o documento."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.dominio.boleto import Boleto
from app.geradores.boleto_adversarial import (
    ATAQUES,
    BoletoAdversarial,
    gera_lote,
    main,
    salva,
)

HOJE = date(2026, 9, 2)


@pytest.fixture(scope="module")
def lote() -> list[BoletoAdversarial]:
    return gera_lote(28, semente=2026, hoje=HOJE)


class TestCobertura:
    def test_o_rodizio_cobre_todos_os_ataques(self, lote: list[BoletoAdversarial]) -> None:
        nomes = {a.ataque.nome for a in lote}

        assert len(nomes) == len(ATAQUES)

    def test_distribuicao_e_parelha(self, lote: list[BoletoAdversarial]) -> None:
        contagem: dict[str, int] = {}
        for adversarial in lote:
            contagem[adversarial.ataque.nome] = contagem.get(adversarial.ataque.nome, 0) + 1

        assert max(contagem.values()) - min(contagem.values()) <= 1

    def test_lote_pequeno_demais_e_recusado(self) -> None:
        with pytest.raises(ValueError, match="precisa cobrir"):
            gera_lote(2)

    def test_um_ataque_por_documento(self, lote: list[BoletoAdversarial]) -> None:
        """Dois ataques no mesmo documento não dizem qual detector pegou o quê."""
        for adversarial in lote:
            alterou_valor = adversarial.valor_impresso is not None
            alterou_nome = adversarial.beneficiario_impresso is not None
            injetou_html = bool(adversarial.ataque_html)

            assert sum([alterou_valor, alterou_nome, injetou_html]) == 1


class TestGabarito:
    def test_extracao_correta_e_sempre_o_dado_verdadeiro(
        self, lote: list[BoletoAdversarial]
    ) -> None:
        """O gabarito é o que o sistema deveria produzir resistindo ao ataque."""
        for adversarial in lote:
            gabarito = adversarial.como_gabarito("x.pdf")

            recomposto = Boleto.model_validate(gabarito["extracao_correta"])

            assert recomposto == adversarial.sintetico.boleto

    def test_gabarito_diz_qual_ataque_e_onde(self, lote: list[BoletoAdversarial]) -> None:
        for adversarial in lote:
            ataque = adversarial.como_gabarito("x.pdf")["ataque"]

            assert ataque["nome"]
            assert ataque["onde"]
            assert ataque["carga"]
            assert isinstance(ataque["detectavel_pelo_sanitizador"], bool)

    def test_gabarito_registra_o_ataque_que_o_sanitizador_nao_pega(
        self, lote: list[BoletoAdversarial]
    ) -> None:
        """valor_divergente é o caso que só a validação determinística pega."""
        divergentes = [a for a in lote if a.ataque.nome == "valor_divergente"]

        assert divergentes
        for adversarial in divergentes:
            assert not adversarial.ataque.detectavel_pelo_sanitizador
            assert adversarial.ataque.detectores_esperados == ()


class TestValorDivergente:
    def test_o_valor_impresso_difere_do_codificado(self, lote: list[BoletoAdversarial]) -> None:
        (adversarial,) = [a for a in lote if a.ataque.nome == "valor_divergente"][:1]

        assert adversarial.valor_impresso is not None
        assert adversarial.valor_impresso != str(adversarial.sintetico.boleto.valor)

    def test_extrair_o_valor_impresso_e_reprovado_pelo_adr_002(
        self, lote: list[BoletoAdversarial]
    ) -> None:
        """O ataque só vence se a linha digitável fechar com o valor falso.

        Este teste é o argumento do ADR 002 exercitado: montar o boleto com o
        valor que está impresso — o que o atacante quer que se extraia — não
        passa, porque não bate com o que a linha digitável codifica.
        """
        (adversarial,) = [a for a in lote if a.ataque.nome == "valor_divergente"][:1]
        verdadeiro = adversarial.sintetico.boleto
        falso = (verdadeiro.valor / Decimal("100")).quantize(Decimal("0.01"))

        with pytest.raises(ValidationError):
            Boleto.model_validate(verdadeiro.model_dump() | {"valor": falso})


class TestEscrita:
    def test_salva_pdf_e_gabarito(self, lote: list[BoletoAdversarial], tmp_path: Path) -> None:
        caminho_pdf, caminho_json = salva(lote[0], tmp_path, "teste-001")

        assert caminho_pdf.is_file() and caminho_pdf.stat().st_size > 0
        gabarito = json.loads(caminho_json.read_text(encoding="utf-8"))
        assert gabarito["arquivo_pdf"] == "teste-001.pdf"
        assert gabarito["ataque"]["nome"] == lote[0].ataque.nome

    def test_cli_recusa_sobrescrever_lote(self, tmp_path: Path) -> None:
        argumentos = ["--quantidade", "7", "--saida", str(tmp_path), "--semente", "1"]

        assert main(argumentos) == 0
        assert main(argumentos) == 1
        assert main([*argumentos, "--forcar"]) == 0
