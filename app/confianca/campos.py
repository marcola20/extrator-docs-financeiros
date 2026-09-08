"""A definição única de "mesmo valor", por campo.

## Por que este módulo existe

Ele nasceu de um erro. O eval comparava o campo bruto do modelo com o
gabarito usando comparação de texto; o pipeline convertia o mesmo campo para
o domínio usando outra regra. Para `banco_codigo` as duas discordavam:
`748-X` e `748` eram iguais para o pipeline e diferentes para o eval.

O efeito foi uma **taxa de escape falsa de 50%** — a métrica principal do
projeto acusando um pagamento errado que não existia, porque o objeto que o
pipeline produziu estava certo. Ver ADR 005.

A causa não foi a regra de nenhum dos dois lados estar errada. Foi haver
duas. Enquanto a definição de igualdade morar em dois lugares, ela vai
divergir de novo, e a divergência aparece justamente na métrica que decide
se o sistema pode existir.

Então a definição mora aqui, e só aqui. Consomem este módulo:

- `app.extracao.extrator.para_dominio` — para converter;
- `app.confianca.grounding` — para conferir presença no texto;
- `eval.py` — para comparar com o gabarito.
"""

import re
from collections.abc import Callable
from enum import StrEnum

from app.confianca import normalizacao

CODIGO_DE_BANCO = re.compile(r"^(\d{3})(?:\s*[-./]?\s*([0-9Xx]))?$")


class TipoDeCampo(StrEnum):
    """Como comparar um campo. Uma classificação, usada pelos três consumidores."""

    DIGITOS = "digitos"
    """Só os dígitos importam: a página formata, o dado não."""

    CODIGO_DE_BANCO = "codigo_de_banco"
    """Três dígitos, com o dígito verificador do banco descartado por regra."""

    VALOR = "valor"
    DATA = "data"
    TEXTO = "texto"


TIPOS: dict[str, TipoDeCampo] = {
    "linha_digitavel": TipoDeCampo.DIGITOS,
    "beneficiario_nome": TipoDeCampo.TEXTO,
    "beneficiario_cnpj": TipoDeCampo.DIGITOS,
    "pagador_nome": TipoDeCampo.TEXTO,
    "pagador_cpf_cnpj": TipoDeCampo.DIGITOS,
    "valor": TipoDeCampo.VALOR,
    "vencimento": TipoDeCampo.DATA,
    "banco_codigo": TipoDeCampo.CODIGO_DE_BANCO,
    "banco_nome": TipoDeCampo.TEXTO,
    "nosso_numero": TipoDeCampo.DIGITOS,
    # Informe de rendimentos (Fase 2). Mesma tabela de propósito: uma segunda
    # definição de igualdade é exatamente o que produziu a taxa de escape
    # falsa de 50% que este módulo existe para não repetir.
    "ano_calendario": TipoDeCampo.DIGITOS,
    "exercicio": TipoDeCampo.DIGITOS,
    "fonte_pagadora_cnpj": TipoDeCampo.DIGITOS,
    "fonte_pagadora_nome": TipoDeCampo.TEXTO,
    "beneficiario_cpf": TipoDeCampo.DIGITOS,
    # `beneficiario_nome` já está declarado acima, pelo boleto. Os dois
    # documentos chamam de beneficiário pessoas diferentes — quem recebe a
    # cobrança e quem recebe o rendimento —, mas a tabela mapeia nome de campo
    # para *como comparar*, e os dois são texto livre. Uma entrada basta.
    "descricao": TipoDeCampo.TEXTO,
    "saldo_31_12": TipoDeCampo.VALOR,
    "saldo_31_12_anterior": TipoDeCampo.VALOR,
    "total_impresso": TipoDeCampo.VALOR,
    "identificador": TipoDeCampo.TEXTO,
    "especificacao": TipoDeCampo.TEXTO,
    # `layout` não está escrito na página com essas palavras: é a
    # classificação que o modelo faz do documento que está lendo. Entra como
    # texto porque é assim que a acurácia contra o gabarito o compara, e o
    # grounding o isenta em vez de procurá-lo no documento.
    "layout": TipoDeCampo.TEXTO,
}


class ValorIlegivel(ValueError):
    """O texto não tem a forma que o campo exige.

    A mensagem aponta a causa e diz a forma aceita, porque o destinatário é
    quem for investigar um eval, não quem escreveu este módulo.
    """


def codigo_do_banco(texto: str) -> str:
    """Extrai os três dígitos do código do banco, descartando o DV impresso.

    O boleto imprime o código com o dígito verificador do banco: `748-X`,
    `001-9`, `341-7`. O dado é o código; o DV é derivável dele
    (`dv_codigo_banco`), então ele não carrega informação nenhuma que o
    código já não tenha.

    **Por que o DV não é conferido.** Seria redundante com uma checagem mais
    forte que já existe: o `model_validator` do `Boleto` cruza `banco_codigo`
    com os três primeiros dígitos da linha digitável, que é protegida por
    quatro dígitos verificadores próprios (ADR 002). Um código lido errado já
    é reprovado lá, com evidência melhor.

    Antes esta separação acontecia por acidente, dentro de um `digitos()`
    genérico: com DV em letra (`748-X`) o resultado saía certo por sorte, e
    com DV numérico (`001-9`) virava `0019`, reprovado com a mensagem
    "código do banco precisa de 3 dígitos" — que culpa o modelo por ter
    copiado corretamente o que estava impresso.
    """
    limpo = texto.strip()
    casamento = CODIGO_DE_BANCO.match(limpo)
    if casamento is None:
        raise ValorIlegivel(
            f"banco_codigo {texto!r} não tem a forma esperada: três dígitos, "
            f"opcionalmente seguidos do dígito verificador do banco "
            f"(ex.: 341 ou 341-7). O boleto costuma imprimir a segunda forma."
        )
    return casamento.group(1)


def _canonico_digitos(texto: str) -> str:
    so_digitos = normalizacao.digitos(texto)
    if not so_digitos:
        raise ValorIlegivel(
            f"{texto!r} não tem nenhum dígito; este campo aceita dígitos, "
            f"com ou sem a pontuação que a página imprime"
        )
    return so_digitos


def _canonico_valor(texto: str) -> str:
    lido = normalizacao.numero(texto)
    if lido is None:
        raise ValorIlegivel(
            f"{texto!r} não é um valor monetário legível "
            f"(formas aceitas: 1.847,30 / 1847,30 / R$ 1.847,30 / 1847.30)"
        )
    return f"{lido:.2f}"


def _canonico_data(texto: str) -> str:
    lida = normalizacao.data(texto)
    if lida is None:
        raise ValorIlegivel(
            f"{texto!r} não é uma data legível "
            f"(formas aceitas: {', '.join(normalizacao.FORMATOS_DE_DATA)})"
        )
    return lida.isoformat()


_CANONICOS: dict[TipoDeCampo, Callable[[str], str]] = {
    TipoDeCampo.DIGITOS: _canonico_digitos,
    TipoDeCampo.CODIGO_DE_BANCO: codigo_do_banco,
    TipoDeCampo.VALOR: _canonico_valor,
    TipoDeCampo.DATA: _canonico_data,
    TipoDeCampo.TEXTO: normalizacao.texto_comparavel,
}


def tipo(campo: str) -> TipoDeCampo:
    """O tipo de comparação do campo. Campo desconhecido é erro, não texto."""
    if campo not in TIPOS:
        raise KeyError(f"campo {campo!r} não tem tipo de comparação declarado")
    return TIPOS[campo]


def canonico(campo: str, valor: str) -> str:
    """A forma canônica do campo. Levanta `ValorIlegivel` quando não dá."""
    return _CANONICOS[tipo(campo)](valor)


def iguais(campo: str, primeiro: str, segundo: str) -> bool:
    """Os dois textos representam o mesmo valor deste campo?

    Vazio só é igual a vazio. Ilegível nunca é igual a nada — nem a outro
    ilegível, porque não se sabe o que nenhum dos dois é.
    """
    a, b = primeiro.strip(), segundo.strip()
    if not a or not b:
        return not a and not b
    try:
        return canonico(campo, a) == canonico(campo, b)
    except ValorIlegivel:
        return False
