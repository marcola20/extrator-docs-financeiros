"""Provedor Anthropic, via SDK oficial.

Não é o provedor padrão: existe para a comparação da Fase 1.3, quando o
resultado do Gemini precisar de um segundo ponto de referência. Mínimo de
propósito — o que ele prova é que o Protocol serve para mais de um SDK.

O módulo se chama `anthropic` dentro de `app.llm`, mas `import anthropic`
aqui resolve o pacote do PyPI: import em Python 3 é absoluto por padrão.
"""

from decimal import Decimal

import anthropic
from pydantic import BaseModel

from app.llm.limitador import Cota
from app.llm.provedor import (
    INSTRUCAO_PADRAO,
    ErroDeConfiguracao,
    ErroDeExtracao,
    ErroDeTaxa,
    Preco,
    ResultadoExtracao,
    UsoDeTokens,
)

NOME = "anthropic"

MODELO_PADRAO = "claude-opus-5"

# Dólar por milhão de tokens, conferido em 2026-09-02.
PRECOS: dict[str, Preco] = {
    "claude-opus-5": Preco(Decimal("5.00"), Decimal("25.00")),
    "claude-sonnet-5": Preco(Decimal("2.00"), Decimal("10.00")),
    "claude-haiku-4-5": Preco(Decimal("1.00"), Decimal("5.00")),
}

MAX_TOKENS = 16_000

# A Anthropic é paga e não impõe uma cota gratuita fixa. O limite aqui é rede
# de segurança contra um laço que torre crédito, não uma regra do provedor.
COTA_PADRAO = Cota(rpm=50, rpd=1_000)


class ProvedorAnthropic:
    """Extrai dados estruturados com o Claude."""

    def __init__(
        self,
        api_key: str,
        modelo: str = MODELO_PADRAO,
        *,
        cliente: anthropic.Anthropic | None = None,
    ) -> None:
        if not api_key and cliente is None:
            raise ErroDeConfiguracao(
                "ANTHROPIC_API_KEY está vazia. Gere uma chave em "
                "https://console.anthropic.com/settings/keys e coloque no .env."
            )
        if modelo not in PRECOS:
            conhecidos = ", ".join(sorted(PRECOS))
            raise ErroDeConfiguracao(
                f"modelo {modelo!r} sem preço cadastrado em app/llm/anthropic.py; "
                f"conhecidos: {conhecidos}"
            )
        self._modelo = modelo
        self._cliente = cliente if cliente is not None else anthropic.Anthropic(api_key=api_key)

    @property
    def nome(self) -> str:
        return NOME

    @property
    def modelo(self) -> str:
        return self._modelo

    def extrai[TSchema: BaseModel](
        self,
        texto: str,
        schema: type[TSchema],
        *,
        instrucao: str = INSTRUCAO_PADRAO,
    ) -> ResultadoExtracao[TSchema]:
        # Sem `temperature`: os modelos atuais recusam parâmetro de amostragem
        # com HTTP 400. O determinismo vem do structured output.
        try:
            resposta = self._cliente.messages.parse(
                model=self._modelo,
                max_tokens=MAX_TOKENS,
                system=instrucao,
                messages=[{"role": "user", "content": texto}],
                output_format=schema,
            )
        except anthropic.RateLimitError as erro:
            cabecalho = erro.response.headers.get("retry-after")
            raise ErroDeTaxa(
                f"Anthropic recusou por excesso de requisições: {erro}",
                espera_sugerida_s=float(cabecalho) if cabecalho else None,
            ) from erro
        except anthropic.APIError as erro:
            raise ErroDeExtracao(f"falha na chamada à Anthropic: {erro}") from erro

        if resposta.stop_reason == "refusal":
            raise ErroDeExtracao(f"Claude recusou a extração: {resposta.stop_details}")

        dados = resposta.parsed_output
        if not isinstance(dados, schema):
            raise ErroDeExtracao(
                f"Anthropic não devolveu um {schema.__name__} válido "
                f"(recebido: {type(dados).__name__})"
            )

        uso = UsoDeTokens(
            entrada=resposta.usage.input_tokens,
            saida=resposta.usage.output_tokens,
        )
        return ResultadoExtracao(
            dados=dados,
            provedor=NOME,
            modelo=self._modelo,
            uso=uso,
            custo_estimado_usd=PRECOS[self._modelo].custo(uso),
        )
