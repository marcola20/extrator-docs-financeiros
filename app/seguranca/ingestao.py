"""Leitura de um PDF não confiável: texto e achados, numa passagem só.

## Por que texto e achados saem juntos

O sanitizador precisa analisar **exatamente o texto que irá ao modelo**. Se
a extração usasse uma leitura e o sanitizador outra — outro filtro, outro
recorte, outra versão da página — abriria uma fresta em que existe texto que
o modelo vê e o sanitizador não olhou. Seria uma defesa conferindo um
artefato diferente do que está em risco.

Então a ingestão é o único ponto que abre o PDF, e devolve os dois lados da
mesma leitura amarrados no `ResultadoSanitizacao`.
"""

from collections.abc import Sequence
from pathlib import Path

import pdfplumber

from app.seguranca.detectores import divergencia_ocr, padroes, texto_invisivel
from app.seguranca.detectores.divergencia_ocr import Bloco, OcrIndisponivel
from app.seguranca.sanitizador import (
    Achado,
    Local,
    ResultadoSanitizacao,
)

DETECTOR_TEXTO_INVISIVEL = "texto_invisivel"
DETECTOR_PADROES = "padroes"
DETECTOR_DIVERGENCIA_OCR = "divergencia_ocr"


def _blocos_da_pagina(pagina: pdfplumber.page.Page, numero: int) -> list[Bloco]:
    """Uma linha da camada de texto por bloco, com a caixa dela."""
    blocos = []
    for linha in pagina.extract_text_lines():
        blocos.append(
            Bloco(
                texto=str(linha["text"]),
                local=Local(
                    pagina=numero,
                    x0=float(linha["x0"]),
                    topo=float(linha["top"]),
                    x1=float(linha["x1"]),
                    base=float(linha["bottom"]),
                ),
            )
        )
    return blocos


def sanitiza(
    caminho: Path,
    *,
    com_ocr: bool = True,
    padroes_carregados: Sequence[padroes.PadraoInjecao] | None = None,
) -> ResultadoSanitizacao:
    """Extrai o texto do PDF e roda os três detectores sobre ele.

    Com `com_ocr=False` o detector de divergência é pulado — ele custa cerca
    de um segundo por página e nem todo ambiente tem tesseract. O resultado
    registra quais detectores rodaram, para ninguém confundir "não achou" com
    "não procurou".
    """
    lista_padroes = (
        tuple(padroes_carregados) if padroes_carregados is not None else padroes.carrega_padroes()
    )

    achados: list[Achado] = []
    partes_do_texto: list[str] = []
    executados = {DETECTOR_TEXTO_INVISIVEL, DETECTOR_PADROES}

    with pdfplumber.open(caminho) as pdf:
        paginas = list(pdf.pages)
        for indice, pagina in enumerate(paginas):
            numero = indice + 1
            texto_da_pagina = pagina.extract_text() or ""
            partes_do_texto.append(texto_da_pagina)

            achados += texto_invisivel.detecta(
                pagina.chars,
                pagina=numero,
                caixa=pagina.bbox,
                rects=pagina.rects,
            )
            achados += padroes.detecta(texto_da_pagina, pagina=numero, padroes=lista_padroes)

            if com_ocr:
                blocos = _blocos_da_pagina(pagina, numero)
                try:
                    lido = divergencia_ocr.texto_da_imagem(str(caminho), indice)
                except OcrIndisponivel:
                    # Sem OCR o documento não fica "limpo": fica sem esse
                    # detector, e o resultado diz isso.
                    com_ocr = False
                else:
                    executados.add(DETECTOR_DIVERGENCIA_OCR)
                    achados += divergencia_ocr.detecta(blocos, lido)

    return ResultadoSanitizacao(
        documento=caminho,
        texto="\n".join(partes_do_texto),
        achados=tuple(achados),
        detectores_executados=frozenset(executados),
    )
