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

## O documento multi-registro

O informe não tem dez campos planos: tem três quadros de linhas, os totais
deles e a tabela de saldos. A conferência é a mesma — o valor está escrito na
página? —, mas cada resposta precisa dizer **de qual linha** ela fala, senão o
relatório diz "valor não aparece" sobre um documento com quarenta valores.
Por isso `Conferencia` carrega `local`, e a função que percorre uma lista de
itens (`confere_itens`) é a mesma para os dois documentos.

Vale marcar o que isso compra de graça: `total_impresso` é conferido como
qualquer outro valor, então um modelo que **soma as linhas** em vez de
transcrever o total — o que tornaria o sinal de aritmética uma tautologia —
devolve um número que não está na página, e cai aqui.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from app.confianca import campos, normalizacao
from app.extracao.schema_transporte import CAMPOS, BoletoExtraido

if TYPE_CHECKING:
    from app.extracao.schema_transporte_informe import InformeExtraido

CAMPOS_ISENTOS: dict[str, str] = {
    "banco_nome": ("derivável de banco_codigo; o cabeçalho pode trazer só a marca do banco"),
}

CAMPOS_ISENTOS_DO_INFORME: dict[str, str] = {
    "layout": (
        "é a classificação do documento, não texto impresso nele; quem diz se "
        "o modelo acertou é a acurácia contra o gabarito"
    ),
    "identificador": (
        "no comprovante a página imprime o número do quadro e o da linha "
        "separados, então `3.1` não aparece literalmente; a chave é medida por "
        "recall e precisão de linha, e não aqui"
    ),
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
    local: str = ""
    """Onde no documento, quando o documento tem mais de um valor por campo.

    Vazio no boleto, onde campo e lugar são a mesma coisa. No informe é
    `rendimentos_isentos[LCI].valor`, e sem ele o relatório diria "valor não
    aparece" sobre um documento com quarenta valores.
    """

    @property
    def onde(self) -> str:
        return self.local or self.campo

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
        return "; ".join(f"{c.onde} não aparece no documento ({c.valor!r})" for c in self.ausentes)


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


def confere_itens(
    itens: Sequence[tuple[str, str, str]],
    texto_de_origem: str,
    *,
    isentos: Mapping[str, str],
) -> ResultadoGrounding:
    """Confere uma lista de `(campo, valor, local)` contra o texto de origem.

    É o percurso, sem saber de qual documento os itens vieram. O boleto passa
    dez itens de local vazio; o informe passa os escalares, os valores de
    linha, os totais e os saldos, cada um com o endereço de onde saiu.
    """
    texto = normalizacao.texto_comparavel(texto_de_origem)
    texto_digitos = normalizacao.digitos(texto_de_origem)

    conferencias = []
    for campo, escrito, local in itens:
        valor = escrito.strip()

        if campo in isentos:
            conferencias.append(Conferencia(campo, Situacao.ISENTO, valor, isentos[campo], local))
        elif not valor:
            conferencias.append(
                Conferencia(campo, Situacao.VAZIO, valor, "o modelo não preencheu", local)
            )
        elif _aparece(campo, valor, texto, texto_digitos):
            conferencias.append(Conferencia(campo, Situacao.ENCONTRADO, valor, "", local))
        else:
            conferencias.append(
                Conferencia(campo, Situacao.AUSENTE, valor, "não aparece no texto de origem", local)
            )
    return ResultadoGrounding(tuple(conferencias))


def confere(bruto: BoletoExtraido, texto_de_origem: str) -> ResultadoGrounding:
    """Confere cada campo extraído contra o texto de onde ele deveria ter saído."""
    itens = [(campo, getattr(bruto, campo), "") for campo in CAMPOS]
    return confere_itens(itens, texto_de_origem, isentos=CAMPOS_ISENTOS)


def confere_informe(bruto: "InformeExtraido", texto_de_origem: str) -> ResultadoGrounding:
    """Confere o informe inteiro: escalares, valores de linha, totais e saldos.

    O achatamento vem de `app.extracao.extrator_informe.valores_extraidos`, e
    não daqui, porque quem sabe a forma do documento é quem o extraiu. Este
    módulo sabe conferir presença, e é só isso que ele faz.
    """
    from app.extracao.extrator_informe import valores_extraidos

    itens = [(v.campo, v.valor, v.local) for v in valores_extraidos(bruto)]
    return confere_itens(itens, texto_de_origem, isentos=CAMPOS_ISENTOS_DO_INFORME)
