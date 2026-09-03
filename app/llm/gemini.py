"""Provedor Gemini, via SDK google-genai.

Provedor padrão do projeto por causa do tier gratuito (ADR 003). Usa o
structured output nativo: o schema Pydantic vai direto em `response_schema` e
a resposta volta já como instância, sem parsing de JSON na mão.

Os identificadores de modelo estão fixos de propósito, sem os apelidos
`-latest`: um alias troca de modelo sozinho e dois evals deixariam de ser
comparáveis sem nada no repositório ter mudado.
"""

from decimal import Decimal

from google import genai
from google.genai import errors as erros_genai
from google.genai import types
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
from app.seguranca.delimitadores import envelopa

NOME = "gemini"

# Modelo de desenvolvimento: cota diária grande, para iterar sem racionar.
MODELO_PADRAO = "gemini-3.5-flash-lite"
# Modelo da comparação final: melhor, e com cota diária que só dá para uma
# passada de eval por dia.
MODELO_COMPARACAO = "gemini-3.8-flash"

# Preço de tabela em dólar por milhão de tokens, conferido em 2026-09-02 na
# página de preços. No tier gratuito nada disso é cobrado; o número existe
# para responder quanto o pipeline custaria pago.
# Atenção: o preço do 3.8-flash dobra em 2027-01-01 ($1.50/$7.50).
PRECOS: dict[str, Preco] = {
    MODELO_PADRAO: Preco(Decimal("0.30"), Decimal("2.50")),
    MODELO_COMPARACAO: Preco(Decimal("0.75"), Decimal("3.75")),
}

# Cotas do tier gratuito. Não saem publicadas na documentação — o número vem
# do painel do AI Studio e precisa ser reconferido lá quando mudar.
COTAS_TIER_GRATUITO: dict[str, Cota] = {
    MODELO_PADRAO: Cota(rpm=15, rpd=500),
    MODELO_COMPARACAO: Cota(rpm=5, rpd=20),
}

HTTP_EXCESSO_DE_REQUISICOES = 429


class ProvedorGemini:
    """Extrai dados estruturados com o Gemini."""

    def __init__(
        self,
        api_key: str,
        modelo: str = MODELO_PADRAO,
        *,
        cliente: genai.Client | None = None,
    ) -> None:
        if not api_key and cliente is None:
            raise ErroDeConfiguracao(
                "GEMINI_API_KEY está vazia. Gere uma chave em "
                "https://aistudio.google.com/apikey e coloque no .env."
            )
        if modelo not in PRECOS:
            conhecidos = ", ".join(sorted(PRECOS))
            raise ErroDeConfiguracao(
                f"modelo {modelo!r} sem preço cadastrado em app/llm/gemini.py; "
                f"conhecidos: {conhecidos}"
            )
        self._modelo = modelo
        self._cliente = cliente if cliente is not None else genai.Client(api_key=api_key)

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
        configuracao = types.GenerateContentConfig(
            system_instruction=instrucao,
            response_mime_type="application/json",
            response_schema=schema,
            # Extração é leitura, não redação: a mesma página tem que dar o
            # mesmo resultado duas vezes.
            temperature=0.0,
            # Desliga o automatic function calling. Não declaramos ferramenta
            # nenhuma — a saída estruturada vem de response_schema —, mas o
            # SDK liga o AFC por padrão e avisa em WARNING a cada processo,
            # poluindo a saída do eval. Desligar é o estado correto, não um
            # silenciador: sem ferramenta não há função a chamar.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        try:
            resposta = self._cliente.models.generate_content(
                model=self._modelo,
                contents=envelopa(texto),
                config=configuracao,
            )
        except erros_genai.ClientError as erro:
            if erro.code == HTTP_EXCESSO_DE_REQUISICOES:
                raise ErroDeTaxa(f"Gemini recusou por excesso de requisições: {erro}") from erro
            raise ErroDeExtracao(f"Gemini recusou a requisição: {erro}") from erro
        except erros_genai.APIError as erro:
            raise ErroDeExtracao(f"falha na chamada ao Gemini: {erro}") from erro

        dados = resposta.parsed
        if not isinstance(dados, schema):
            raise ErroDeExtracao(
                f"Gemini não devolveu um {schema.__name__} válido "
                f"(recebido: {type(dados).__name__})"
            )

        uso = self._uso(resposta)
        return ResultadoExtracao(
            dados=dados,
            provedor=NOME,
            modelo=self._modelo,
            uso=uso,
            custo_estimado_usd=PRECOS[self._modelo].custo(uso),
        )

    @staticmethod
    def _uso(resposta: types.GenerateContentResponse) -> UsoDeTokens:
        """Traduz o `usage_metadata` do SDK.

        Os tokens de raciocínio (`thoughts_token_count`) entram na saída porque
        é assim que o Gemini os cobra — ignorá-los subestimaria o custo.
        """
        bruto = resposta.usage_metadata
        if bruto is None:
            return UsoDeTokens(entrada=0, saida=0)
        return UsoDeTokens(
            entrada=bruto.prompt_token_count or 0,
            saida=(bruto.candidates_token_count or 0) + (bruto.thoughts_token_count or 0),
        )
