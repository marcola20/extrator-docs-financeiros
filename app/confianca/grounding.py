"""Sinal 2: o valor extraído aparece literalmente no texto de origem?

É a pergunta mais barata que existe contra alucinação. O modelo devolveu
`beneficiario_cnpj: 03.721.465/0001-20`; esse CNPJ está escrito na página, ou
o modelo o produziu? A conferência é textual e determinística — não pergunta
nada ao modelo, e por isso não compartilha o erro dele.

## Isenção é declarada, nunca silenciosa

Alguns campos não têm correspondência literal esperada. `banco_nome` pode ser
deduzido de `banco_codigo` sem estar impresso por extenso, e um boleto que
mostre só a marca do banco no cabeçalho ainda assim permite preencher o campo.

Reprovar esses campos geraria falso positivo constante; aprová-los em silêncio
seria pior, porque o relatório diria "grounding ok" sobre um campo que nunca
foi conferido. Então eles saem como **ISENTO**, com o motivo escrito, e quem
lê o resultado vê a diferença entre conferido e dispensado.

## O que este sinal não cobre

Presença literal não é correção. Um CNPJ que aparece na página mas pertence ao
pagador, e não ao beneficiário, passa aqui — o campo está trocado e o texto
contém os dois. Grounding pega invenção, não troca de campo.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.confianca import normalizacao
from app.extracao.schema_transporte import CAMPOS, BoletoExtraido

CAMPOS_ISENTOS: dict[str, str] = {
    "banco_nome": ("derivável de banco_codigo; o cabeçalho pode trazer só a marca do banco"),
}

CAMPOS_DE_DIGITOS = frozenset(
    {"linha_digitavel", "beneficiario_cnpj", "pagador_cpf_cnpj", "banco_codigo", "nosso_numero"}
)
CAMPOS_DE_VALOR = frozenset({"valor"})
CAMPOS_DE_DATA = frozenset({"vencimento"})


class Situacao(StrEnum):
    """O que se sabe sobre um campo depois da conferência."""

    ENCONTRADO = "encontrado"
    AUSENTE = "ausente"
    ISENTO = "isento"
    VAZIO = "vazio"


@dataclass(frozen=True, slots=True)
class Conferencia:
    """O resultado da conferência de um campo."""

    campo: str
    situacao: Situacao
    valor: str
    motivo: str = ""

    @property
    def reprova(self) -> bool:
        return self.situacao is Situacao.AUSENTE


@dataclass(frozen=True, slots=True)
class ResultadoGrounding:
    """A conferência de todos os campos."""

    conferencias: tuple[Conferencia, ...]

    @property
    def ausentes(self) -> tuple[Conferencia, ...]:
        return tuple(c for c in self.conferencias if c.reprova)

    @property
    def aprovado(self) -> bool:
        return not self.ausentes

    @property
    def taxa(self) -> float:
        """Fração dos campos conferíveis que foram encontrados."""
        confereveis = [
            c for c in self.conferencias if c.situacao in (Situacao.ENCONTRADO, Situacao.AUSENTE)
        ]
        if not confereveis:
            return 1.0
        return sum(1 for c in confereveis if c.situacao is Situacao.ENCONTRADO) / len(confereveis)

    def descricao(self) -> str:
        if self.aprovado:
            return "todos os campos conferíveis aparecem no documento"
        return "; ".join(f"{c.campo} não aparece no documento ({c.valor!r})" for c in self.ausentes)


def _aparece(campo: str, valor: str, texto: str, texto_digitos: str) -> bool:
    """Confere presença literal, tolerando a formatação da página."""
    if campo in CAMPOS_DE_DIGITOS:
        so_digitos = normalizacao.digitos(valor)
        return bool(so_digitos) and so_digitos in texto_digitos

    if campo in CAMPOS_DE_VALOR:
        lido = normalizacao.numero(valor)
        if lido is None:
            return False
        return any(
            normalizacao.texto_comparavel(forma) in texto
            for forma in normalizacao.valor_como_impresso(lido)
        )

    if campo in CAMPOS_DE_DATA:
        lida = normalizacao.data(valor)
        if lida is None:
            return False
        return any(
            normalizacao.texto_comparavel(forma) in texto
            for forma in normalizacao.data_como_impressa(lida)
        )

    return normalizacao.texto_comparavel(valor) in texto


def confere(bruto: BoletoExtraido, texto_de_origem: str) -> ResultadoGrounding:
    """Confere cada campo extraído contra o texto de onde ele deveria ter saído."""
    texto = normalizacao.texto_comparavel(texto_de_origem)
    texto_digitos = normalizacao.digitos(texto_de_origem)

    conferencias = []
    for campo in CAMPOS:
        valor = getattr(bruto, campo).strip()

        if campo in CAMPOS_ISENTOS:
            conferencias.append(Conferencia(campo, Situacao.ISENTO, valor, CAMPOS_ISENTOS[campo]))
        elif not valor:
            conferencias.append(Conferencia(campo, Situacao.VAZIO, valor, "o modelo não preencheu"))
        elif _aparece(campo, valor, texto, texto_digitos):
            conferencias.append(Conferencia(campo, Situacao.ENCONTRADO, valor))
        else:
            conferencias.append(
                Conferencia(campo, Situacao.AUSENTE, valor, "não aparece no texto de origem")
            )
    return ResultadoGrounding(tuple(conferencias))
