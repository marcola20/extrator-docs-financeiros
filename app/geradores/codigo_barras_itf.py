"""Desenho do código de barras Intercalado 2 de 5, o padrão usado em boleto.

Cada dígito vira cinco elementos, dois deles largos. Os dígitos são lidos aos
pares: o primeiro do par vira as barras e o segundo, os espaços entre elas.
"""

from collections.abc import Iterator

LARGO = "w"
ESTREITO = "n"

PADROES = {
    "0": "nnwwn",
    "1": "wnnnw",
    "2": "nwnnw",
    "3": "wwnnn",
    "4": "nnwnw",
    "5": "wnwnn",
    "6": "nwwnn",
    "7": "nnnww",
    "8": "wnnwn",
    "9": "nwnwn",
}

_INICIO = "nnnn"
"""Barra, espaço, barra e espaço estreitos."""

_FIM = "wnn"
"""Barra larga, espaço estreito e barra estreita."""

RAZAO_LARGO = 3
"""Quantas vezes o elemento largo é mais largo que o estreito."""


def elementos(digitos: str) -> Iterator[tuple[bool, int]]:
    """Percorre o código gerando (é_barra, largura_em_unidades) na ordem do desenho."""
    if not digitos.isdigit():
        raise ValueError(f"código de barras espera apenas dígitos, recebido {digitos!r}")
    if len(digitos) % 2 != 0:
        raise ValueError(f"código de barras precisa de uma quantidade par de dígitos: {digitos!r}")

    for indice, simbolo in enumerate(_INICIO):
        yield indice % 2 == 0, _largura(simbolo)

    for posicao in range(0, len(digitos), 2):
        padrao_barras = PADROES[digitos[posicao]]
        padrao_espacos = PADROES[digitos[posicao + 1]]
        for barra, espaco in zip(padrao_barras, padrao_espacos, strict=True):
            yield True, _largura(barra)
            yield False, _largura(espaco)

    for indice, simbolo in enumerate(_FIM):
        yield indice % 2 == 0, _largura(simbolo)


def svg(digitos: str, *, unidade_mm: float = 0.35, altura_mm: float = 13.0) -> str:
    """Devolve o código de barras como um SVG pronto para embutir no HTML."""
    partes: list[str] = []
    x = 0.0
    for e_barra, unidades in elementos(digitos):
        largura = unidades * unidade_mm
        if e_barra:
            partes.append(
                f'<rect x="{x:.3f}" y="0" width="{largura:.3f}" height="{altura_mm:.3f}"/>'
            )
        x += largura

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{x:.3f}mm" height="{altura_mm:.3f}mm" '
        f'viewBox="0 0 {x:.3f} {altura_mm:.3f}" fill="#000" shape-rendering="crispEdges">'
        f"{''.join(partes)}"
        f"</svg>"
    )


def _largura(simbolo: str) -> int:
    """Traduz o símbolo do padrão na largura em unidades."""
    if simbolo == LARGO:
        return RAZAO_LARGO
    if simbolo == ESTREITO:
        return 1
    raise ValueError(f"símbolo desconhecido no padrão: {simbolo!r}")
