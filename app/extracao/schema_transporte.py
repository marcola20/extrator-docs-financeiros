"""Schema de transporte: o que o modelo devolve, antes de virar domínio.

## Por que não pedir o `Boleto` direto ao modelo

O `Boleto` do ADR 002 cruza banco, valor e vencimento contra a linha
digitável e recusa a instância inteira quando um deles não fecha. É o que dá
a garantia — e é exatamente o que impede usá-lo como formato de saída do
modelo, por duas razões:

**Perderia a acurácia por campo.** Se o modelo lê nove campos certos e erra o
valor, o `Boleto` não instancia e o resultado é "falhou". O eval não
conseguiria dizer que nove campos estavam certos, e não daria para distinguir
um modelo que erra um campo de um que erra tudo.

**Perderia a evidência.** O grounding pergunta se o valor extraído aparece
literalmente no texto de origem. Para isso é preciso ter o que o modelo
**escreveu**, não uma versão já convertida: `Decimal("1847.30")` não diz se o
modelo escreveu `1.847,30`, `1847,30` ou `R$ 1.847,30`.

Então o transporte é todo em texto, sem validador nenhum. A conversão para
`Boleto` acontece depois e **é** o sinal de dígito verificador: se ela levanta
`ValidationError`, o documento não fecha, e isso é informação, não acidente.
"""

from pydantic import BaseModel, Field

CAMPOS = (
    "linha_digitavel",
    "beneficiario_nome",
    "beneficiario_cnpj",
    "pagador_nome",
    "pagador_cpf_cnpj",
    "valor",
    "vencimento",
    "banco_codigo",
    "banco_nome",
    "nosso_numero",
)


class BoletoExtraido(BaseModel):
    """Os campos do boleto como o modelo os escreveu, sem conversão."""

    # Sem `extra="forbid"`: ele faz o Pydantic emitir `additionalProperties`
    # no JSON Schema, e a API do Gemini recusa a requisição com
    # 400 INVALID_ARGUMENT — `Unknown name "additional_properties"`. O SDK
    # aceita o schema localmente; quem recusa é o serviço, então isso só
    # aparece numa chamada de verdade.
    linha_digitavel: str = Field(
        default="", description="Os 47 dígitos da linha digitável, como impressos"
    )
    beneficiario_nome: str = Field(default="", description="Nome do beneficiário")
    beneficiario_cnpj: str = Field(default="", description="CNPJ do beneficiário")
    pagador_nome: str = Field(default="", description="Nome do pagador")
    pagador_cpf_cnpj: str = Field(default="", description="CPF ou CNPJ do pagador")
    valor: str = Field(default="", description="Valor do documento, como impresso")
    vencimento: str = Field(default="", description="Data de vencimento, como impressa")
    banco_codigo: str = Field(default="", description="Código de três dígitos do banco")
    banco_nome: str = Field(default="", description="Nome do banco emissor")
    nosso_numero: str = Field(default="", description="Nosso número, se houver")

    def preenchidos(self) -> dict[str, str]:
        """Só os campos que o modelo realmente respondeu."""
        return {campo: valor for campo in CAMPOS if (valor := getattr(self, campo).strip())}
