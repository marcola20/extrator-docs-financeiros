"""Exercita o uso real do SDK da Anthropic com cliente dublê — sem rede."""

from decimal import Decimal
from typing import Any, cast

import anthropic
import pytest
from anthropic.types import ParsedMessage, ParsedTextBlock, Usage

from app.llm.anthropic import ProvedorAnthropic
from app.llm.provedor import ErroDeConfiguracao
from tests.llm.falso import DocumentoFalso

DOCUMENTO = DocumentoFalso(titulo="Boleto", valor=Decimal("1234.56"))


class _MensagensFalsas:
    def __init__(self, resposta: object | None = None, erro: Exception | None = None) -> None:
        self._resposta = resposta
        self._erro = erro
        self.chamadas: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> object:
        self.chamadas.append(kwargs)
        if self._erro is not None:
            raise self._erro
        return self._resposta


class _ClienteAnthropicFalso:
    def __init__(self, resposta: object | None = None, erro: Exception | None = None) -> None:
        self.messages = _MensagensFalsas(resposta, erro)


def _resposta_anthropic() -> ParsedMessage[DocumentoFalso]:
    return ParsedMessage[DocumentoFalso](
        id="msg_teste",
        model="claude-opus-5",
        role="assistant",
        type="message",
        stop_reason="end_turn",
        content=[
            ParsedTextBlock[DocumentoFalso](
                type="text",
                text=DOCUMENTO.model_dump_json(),
                parsed_output=DOCUMENTO,
            )
        ],
        usage=Usage(input_tokens=1_000, output_tokens=200),
    )


def _provedor_anthropic(cliente: _ClienteAnthropicFalso) -> ProvedorAnthropic:
    return ProvedorAnthropic("", cliente=cast(anthropic.Anthropic, cliente))


def test_anthropic_devolve_instancia_validada_e_custo() -> None:
    cliente = _ClienteAnthropicFalso(_resposta_anthropic())

    resultado = _provedor_anthropic(cliente).extrai("texto", DocumentoFalso)

    assert resultado.dados.valor == Decimal("1234.56")
    assert resultado.provedor == "anthropic"
    # 1000 * 5.00/1e6 + 200 * 25.00/1e6
    assert resultado.custo_estimado_usd == Decimal("0.010000")


def test_anthropic_nao_manda_temperature() -> None:
    """Os modelos atuais recusam parâmetro de amostragem com HTTP 400."""
    cliente = _ClienteAnthropicFalso(_resposta_anthropic())

    _provedor_anthropic(cliente).extrai("texto", DocumentoFalso)

    (chamada,) = cliente.messages.chamadas
    assert "temperature" not in chamada
    assert chamada["output_format"] is DocumentoFalso


def test_anthropic_sem_chave_e_sem_cliente_falha_claro() -> None:
    with pytest.raises(ErroDeConfiguracao, match="ANTHROPIC_API_KEY"):
        ProvedorAnthropic("")
