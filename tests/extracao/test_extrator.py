"""Conversão do transporte para o domínio — que é o sinal de dígito verificador."""

import json
from pathlib import Path

import pytest

from app.extracao.extrator import para_dominio
from app.extracao.schema_transporte import CAMPOS, BoletoExtraido

GABARITO = json.loads(Path("dados/sinteticos/boletos/boleto-001.json").read_text("utf-8"))["campos"]


def _bruto(**campos: str) -> BoletoExtraido:
    base = {k: ("" if v is None else str(v)) for k, v in GABARITO.items()}
    return BoletoExtraido(**(base | campos))


class TestSchemaDeTransporte:
    def test_e_todo_texto_e_sem_validador(self) -> None:
        """Um campo errado não pode derrubar os outros nove."""
        bruto = BoletoExtraido(valor="não é um número", linha_digitavel="xyz")

        assert bruto.valor == "não é um número"

    def test_nao_emite_additional_properties(self) -> None:
        """A API do Gemini recusa esse campo com 400 INVALID_ARGUMENT."""
        assert "additionalProperties" not in BoletoExtraido.model_json_schema()

    def test_preenchidos_ignora_campo_em_branco(self) -> None:
        bruto = BoletoExtraido(valor="10,00", beneficiario_nome="  ")

        assert bruto.preenchidos() == {"valor": "10,00"}

    def test_cobre_todos_os_campos_do_dominio(self) -> None:
        assert set(CAMPOS) == set(BoletoExtraido.model_fields)


class TestConversao:
    def test_extracao_fiel_fecha_no_dominio(self) -> None:
        dominio, erro = para_dominio(_bruto())

        assert dominio is not None, erro
        assert erro is None

    def test_aceita_valor_na_forma_impressa(self) -> None:
        """O modelo devolve o que está na página: 3.112,30."""
        dominio, erro = para_dominio(_bruto(valor="3.112,30"))

        assert dominio is not None, erro

    def test_aceita_data_na_forma_impressa(self) -> None:
        dominio, erro = para_dominio(_bruto(vencimento="19/11/2026"))

        assert dominio is not None, erro

    def test_aceita_linha_digitavel_formatada(self) -> None:
        formatada = GABARITO["linha_digitavel"]
        com_pontos = f"{formatada[:5]}.{formatada[5:10]} {formatada[10:]}"

        dominio, erro = para_dominio(_bruto(linha_digitavel=com_pontos))

        assert dominio is not None, erro


class TestConversaoReprova:
    def test_valor_que_nao_bate_com_a_linha_e_reprovado(self) -> None:
        """É o ADR 002: o ataque de valor divergente morre aqui."""
        dominio, erro = para_dominio(_bruto(valor="1,00"))

        assert dominio is None
        assert erro is not None
        assert "linha digitável" in erro

    def test_valor_ilegivel_e_reprovado_com_motivo(self) -> None:
        dominio, erro = para_dominio(_bruto(valor="grátis"))

        assert dominio is None
        assert erro is not None
        assert "valor" in erro

    @pytest.mark.parametrize("campo", ["linha_digitavel", "beneficiario_cnpj"])
    def test_campo_de_digitos_invalido_e_reprovado(self, campo: str) -> None:
        dominio, _ = para_dominio(_bruto(**{campo: "000"}))

        assert dominio is None
