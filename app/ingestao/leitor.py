"""Ponto único de leitura de um PDF de origem não confiável.

Abre o arquivo uma vez e devolve, amarrados, o texto que irá ao modelo e os
achados da sanitização sobre **esse mesmo texto**.

## Detecção da camada de texto

Um PDF digitalizado é uma imagem dentro de um PDF: `page.chars` vem vazio e
`extract_text()` devolve string vazia. Um boleto gerado digitalmente tem cerca
de 180 tokens de texto. Os dois casos não ficam perto um do outro, então o
limiar não é delicado — mas ele existe para o caso do meio, o PDF que tem uma
camada de texto residual (um carimbo, um número de protocolo) e o resto em
imagem. Esse caso vai para visão, porque a camada residual não é o documento.

## O caminho de visão não tem defesa da Fase 1.2

Vale dizer aqui e não só no ADR: os três detectores operam sobre a camada de
texto. Sem ela, todos rodam sobre nada e não acham nada — e "não achou" não é
"está limpo". Documento lido por visão nunca é auto-aprovável. Ver ADR 005.
"""

import unicodedata
from pathlib import Path

import pypdfium2

from app.ingestao.documento import CaminhoDeLeitura, DocumentoIngerido
from app.seguranca.ingestao import sanitiza

MINIMO_DE_TOKENS = 20
"""Abaixo disto a camada de texto não é o documento. Boleto limpo tem ~180."""

MINIMO_DE_LETRAS = 60
"""Um número de protocolo solto não faz uma camada de texto."""

DPI_VISAO = 200
"""Mesma resolução usada pelo detector de divergência texto/imagem."""

AVISO_SEM_COBERTURA = (
    "documento lido por visão: os detectores da Fase 1.2 operam sobre a "
    "camada de texto e não tiveram o que inspecionar"
)


def _letras(texto: str) -> int:
    return sum(1 for c in texto if unicodedata.category(c).startswith(("L", "N")))


def camada_de_texto_util(texto: str) -> bool:
    """Diz se a camada de texto é o documento, e não um resíduo."""
    return len(texto.split()) >= MINIMO_DE_TOKENS and _letras(texto) >= MINIMO_DE_LETRAS


def rasteriza(caminho: Path, *, dpi: int = DPI_VISAO) -> tuple[bytes, ...]:
    """Renderiza cada página como PNG, para o caminho de visão."""
    import io

    documento = pypdfium2.PdfDocument(str(caminho))
    try:
        paginas = []
        for indice in range(len(documento)):
            imagem = documento[indice].render(scale=dpi / 72).to_pil()
            buffer = io.BytesIO()
            imagem.save(buffer, format="PNG")
            paginas.append(buffer.getvalue())
        return tuple(paginas)
    finally:
        documento.close()


def ingere(caminho: Path, *, com_ocr: bool = True) -> DocumentoIngerido:
    """Lê o PDF, sanitiza, e decide por qual caminho o conteúdo segue."""
    resultado = sanitiza(caminho, com_ocr=com_ocr)

    if camada_de_texto_util(resultado.texto):
        return DocumentoIngerido(
            caminho=caminho,
            leitura=CaminhoDeLeitura.TEXTO,
            texto=resultado.texto,
            sanitizacao=resultado,
            metadados={"tokens_na_camada": str(len(resultado.texto.split()))},
        )

    return DocumentoIngerido(
        caminho=caminho,
        leitura=CaminhoDeLeitura.VISAO,
        texto=resultado.texto,
        sanitizacao=resultado,
        paginas_png=rasteriza(caminho),
        aviso=AVISO_SEM_COBERTURA,
        metadados={"tokens_na_camada": str(len(resultado.texto.split()))},
    )
