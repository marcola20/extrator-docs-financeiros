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

from app.confianca import campos, normalizacao
from app.extracao.schema_transporte import CAMPOS, BoletoExtraido

CAMPOS_ISENTOS: dict[str, str] = {
    "banco_nome": ("derivável de banco_codigo; o cabeçalho pode trazer só a marca do banco"),
}

# A classificação dos campos não mora aqui: ela é a mesma que a conversão
# para o domínio e o eval usam, e vem de `app.confianca.campos`. Duas cópias
# desta tabela foi o que produziu a taxa de escape falsa do ADR 005.


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
    """Confere presença literal, tolerando a formatação da página.

    A operação muda com o tipo do campo — dígitos procuram em dígitos, valor
    procura nas formas em que ele pode estar impresso —, mas **qual** é o
    tipo de cada campo vem da tabela compartilhada.
    """
    try:
        forma = campos.canonico(campo, valor)
    except campos.ValorIlegivel:
        # O modelo escreveu algo que este campo não comporta. Não dá para
        # dizer que aparece no documento: não dá nem para dizer o que é.
        return False

    match campos.tipo(campo):
        case campos.TipoDeCampo.DIGITOS:
            return forma in texto_digitos

        case campos.TipoDeCampo.CODIGO_DE_BANCO:
            # O código impresso vem colado ao DV do banco (`748-X`), então
            # procurar os três dígitos dentro dos dígitos da página basta.
            return forma in texto_digitos

        case campos.TipoDeCampo.VALOR:
            lido = normalizacao.numero(forma)
            return lido is not None and any(
                normalizacao.texto_comparavel(impresso) in texto
                for impresso in normalizacao.valor_como_impresso(lido)
            )

        case campos.TipoDeCampo.DATA:
            lida = normalizacao.data(forma)
            return lida is not None and any(
                normalizacao.texto_comparavel(impresso) in texto
                for impresso in normalizacao.data_como_impressa(lida)
            )

        case campos.TipoDeCampo.TEXTO:
            return forma in texto


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
