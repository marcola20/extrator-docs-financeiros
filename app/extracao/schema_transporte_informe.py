"""Schema de transporte do informe: o que o modelo devolve, antes de virar domínio.

Mesma razão do transporte do boleto (ver `schema_transporte`, e o ADR 006):
tudo em texto, sem validador nenhum, para a conversão ao domínio **ser** o
sinal — se ela levanta `ValidationError`, o documento não fecha, e isso é
informação. E para o grounding poder perguntar se o modelo escreveu
`1.847,30` ou `1847.30`, o que um `Decimal` já convertido não diria.

## O que muda em relação ao boleto: o documento é multi-registro

O boleto cabe em dez campos planos. O informe é uma árvore — três quadros,
cada um com uma lista de linhas e às vezes um total, mais a tabela de saldos.
Três consequências para o formato:

**Os três quadros são posições fixas, não uma lista.** O modelo não escolhe
quantos quadros existem nem como se chamam: tributáveis, isentos e exclusivos
são campos do schema. Uma lista de quadros nomeados pelo modelo transformaria
"o quadro 4 virou 'Rendimentos Isentos e Não Tributáveis (RIN)'" em quadro
faltando, e a métrica de linha mediria a nomenclatura em vez da leitura.

**`total_impresso` vazio quer dizer "a página não imprime total".** É o campo
mais delicado do schema, e o prompt gasta um parágrafo nele: um modelo que
soma as linhas e devolve o resultado faz a conferência de quadro concordar
consigo mesma sempre, e o sinal de aritmética — o único que pega
`linha_injetada` e `total_adulterado` — vira tautologia. Ver ADR 007.

**`identificador` é a chave de casamento, e a origem dela muda com o layout.**
No comprovante de fonte pagadora é o número da linha no formulário (`3.1`), que
a página imprime partido: o quadro traz `3.` no cabeçalho e a linha traz `1.`.
O prompt manda compor os dois. No informe bancário é a especificação impressa,
copiada como está. Ver ADR 007 e `app.avaliacao.linhas`.

`titulo` e o identificador do próprio quadro ficam de fora: são rótulo
tipográfico, não dado, e no layout bancário o quadro nem tem número impresso.
Quem os quiser tem a posição no schema.
"""

from pydantic import BaseModel, Field

from app.dominio.informe import CAMPOS_DE_LINHA, CAMPOS_DE_SALDO, CAMPOS_ESCALARES

CAMPOS = ("layout", *CAMPOS_ESCALARES)
"""Os campos de nível de documento, comparáveis um a um como no boleto.

`layout` entra porque o domínio precisa dele — dois validadores do `Informe`
dependem de qual documento se está lendo — e sai medido como qualquer outro
campo. Ele é o único campo de classificação do schema: não está escrito na
página com essas palavras, então o grounding o isenta, e o que diz se o modelo
acertou é a acurácia contra o gabarito.
"""

NOMES_DOS_QUADROS = (
    "rendimentos_tributaveis",
    "rendimentos_isentos",
    "rendimentos_exclusivos",
)

__all__ = [
    "CAMPOS",
    "CAMPOS_DE_LINHA",
    "CAMPOS_DE_SALDO",
    "NOMES_DOS_QUADROS",
    "InformeExtraido",
    "LinhaExtraida",
    "QuadroExtraido",
    "SaldoExtraido",
]


# Sem `extra="forbid"` em nenhuma classe daqui: ele faz o Pydantic emitir
# `additionalProperties` no JSON Schema, e a API do Gemini recusa a requisição
# com 400 INVALID_ARGUMENT. Está registrado igual no transporte do boleto,
# porque só aparece numa chamada de verdade.
class LinhaExtraida(BaseModel):
    """Uma linha de quadro como o modelo a escreveu."""

    identificador: str = Field(
        default="",
        description=(
            "Chave da linha. No comprovante numerado, o número do quadro e o "
            "da linha juntos: 3.1, 4.7, 5.2. No informe bancário, a "
            "especificação impressa, copiada como está: 'CDB 8056747'"
        ),
    )
    descricao: str = Field(default="", description="Descrição da linha, como impressa")
    valor: str = Field(default="", description="Valor da linha, como impresso")


class QuadroExtraido(BaseModel):
    """Um quadro: as linhas e o total, quando a página imprime um."""

    linhas: list[LinhaExtraida] = Field(default_factory=list)
    total_impresso: str = Field(
        default="",
        description=(
            "O total que a página imprime para este quadro, como impresso. "
            "Vazio se a página não imprimir total. Nunca some as linhas para "
            "preencher este campo"
        ),
    )


class SaldoExtraido(BaseModel):
    """Uma linha da tabela de saldos em 31/12, só no informe bancário."""

    especificacao: str = Field(
        default="", description="Especificação da conta ou aplicação, como impressa"
    )
    saldo_31_12: str = Field(
        default="", description="Saldo em 31/12 do ano-calendário deste informe"
    )
    saldo_31_12_anterior: str = Field(
        default="", description="Saldo em 31/12 do ano anterior ao deste informe"
    )


class InformeExtraido(BaseModel):
    """O informe como o modelo o escreveu, sem conversão."""

    layout: str = Field(
        default="",
        description=(
            "fonte_pagadora para o Comprovante de Rendimentos Pagos, de linhas "
            "numeradas e sem tabela de saldos; instituicao_financeira para o "
            "informe anual de rendimentos financeiros, com saldos em 31/12"
        ),
    )
    ano_calendario: str = Field(default="", description="Ano-calendário, como impresso")
    exercicio: str = Field(default="", description="Exercício, como impresso")
    fonte_pagadora_cnpj: str = Field(default="", description="CNPJ da fonte pagadora")
    fonte_pagadora_nome: str = Field(default="", description="Nome da fonte pagadora")
    beneficiario_cpf: str = Field(default="", description="CPF do beneficiário")
    beneficiario_nome: str = Field(default="", description="Nome do beneficiário")
    rendimentos_tributaveis: QuadroExtraido = Field(default_factory=QuadroExtraido)
    rendimentos_isentos: QuadroExtraido = Field(default_factory=QuadroExtraido)
    rendimentos_exclusivos: QuadroExtraido = Field(default_factory=QuadroExtraido)
    saldos: list[SaldoExtraido] = Field(default_factory=list)

    def quadros(self) -> tuple[tuple[str, QuadroExtraido], ...]:
        """Os três quadros com o nome do campo, na ordem do documento."""
        return tuple((nome, getattr(self, nome)) for nome in NOMES_DOS_QUADROS)

    def preenchidos(self) -> dict[str, str]:
        """Só os campos escalares que o modelo realmente respondeu."""
        return {campo: valor for campo in CAMPOS if (valor := getattr(self, campo).strip())}

    @property
    def total_de_linhas(self) -> int:
        return sum(len(quadro.linhas) for _, quadro in self.quadros())
