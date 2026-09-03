"""Normalização compartilhada entre conversão e grounding.

`1.847,30`, `1847,30`, `R$ 1.847,30` e `1847.30` são o mesmo valor, e
`19/11/2026`, `19-11-2026` e `2026-11-19` são a mesma data. Quem converte
para o domínio e quem confere se o valor aparece no texto de origem precisam
concordar sobre isso, senão o grounding reprova extração correta só porque o
modelo copiou a formatação impressa.

Um único módulo, então, e as duas pontas usam o mesmo.
"""

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

_NAO_DIGITO = re.compile(r"\D")
_ESPACOS = re.compile(r"\s+")
_SIMBOLO_MOEDA = re.compile(r"(?i)(r\$|rs\b|brl\b)")

FORMATOS_DE_DATA = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y")


def digitos(texto: str) -> str:
    """Só os dígitos, para linha digitável, CPF e CNPJ."""
    return _NAO_DIGITO.sub("", texto)


def texto_comparavel(texto: str) -> str:
    """Minúsculas, sem acento, espaços colapsados."""
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return _ESPACOS.sub(" ", sem_acento).strip()


def numero(texto: str) -> Decimal | None:
    """Lê um valor monetário escrito em qualquer das formas usuais.

    Devolve `Decimal`, nunca `float` — é dinheiro (ver CLAUDE.md). Devolve
    `None` quando o texto não é um número, e quem chama decide o que fazer.
    """
    limpo = _SIMBOLO_MOEDA.sub("", texto).strip()
    limpo = _ESPACOS.sub("", limpo)
    if not limpo:
        return None

    tem_virgula, tem_ponto = "," in limpo, "." in limpo
    if tem_virgula and tem_ponto:
        # O separador decimal é o que aparece por último: 1.847,30 ou 1,847.30
        decimal_e_virgula = limpo.rfind(",") > limpo.rfind(".")
        limpo = (
            limpo.replace(".", "").replace(",", ".")
            if decimal_e_virgula
            else limpo.replace(",", "")
        )
    elif tem_virgula:
        limpo = limpo.replace(",", ".")
    elif tem_ponto and len(limpo.split(".")[-1]) == 3:
        # 1.847 é milhar, não 1 real e 847 milésimos.
        limpo = limpo.replace(".", "")

    try:
        return Decimal(limpo)
    except InvalidOperation:
        return None


def data(texto: str) -> date | None:
    """Lê uma data escrita em qualquer dos formatos usuais."""
    from datetime import datetime

    limpo = texto.strip()
    for formato in FORMATOS_DE_DATA:
        try:
            return datetime.strptime(limpo, formato).date()
        except ValueError:
            continue
    return None


def valor_como_impresso(valor: Decimal) -> list[str]:
    """As formas em que um valor pode estar escrito na página.

    Usado pelo grounding: se o modelo devolveu 1847.30, o texto de origem
    pode trazer `1.847,30`, `1847,30` ou `1847.30`. Todas contam como a
    mesma coisa aparecendo literalmente.
    """
    inteiro, _, centavos = f"{valor:.2f}".partition(".")
    com_milhar = f"{int(inteiro):,}".replace(",", ".")
    return [
        f"{com_milhar},{centavos}",
        f"{inteiro},{centavos}",
        f"{inteiro}.{centavos}",
    ]


def data_como_impressa(dia: date) -> list[str]:
    """As formas em que uma data pode estar escrita na página."""
    return [
        dia.strftime("%d/%m/%Y"),
        dia.strftime("%d-%m-%Y"),
        dia.strftime("%d.%m.%Y"),
        dia.isoformat(),
    ]
