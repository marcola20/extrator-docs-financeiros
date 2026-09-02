"""Taxa de falso positivo do sanitizador no corpus limpo.

É o teste que ancora todos os limiares. Os 15 boletos sintéticos existentes
são documentos honestos, gerados antes de a defesa existir e sem nenhum
ataque dentro. **Nenhum deles pode ser sinalizado.** Se um for, o limiar
está errado — e o erro é caro nos dois sentidos: falso positivo manda
documento bom para a fila de revisão, e afrouxar o limiar para calar o
alarme cega o detector.

Roda os três detectores, OCR incluído, e por isso leva alguns segundos.
"""

import shutil
from pathlib import Path

import pytest

from app.seguranca.ingestao import DETECTOR_DIVERGENCIA_OCR, sanitiza
from app.seguranca.politica import Rota, decide

CORPUS_LIMPO = Path("dados/sinteticos/boletos")

tem_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="tesseract não instalado; a divergência texto/imagem não roda",
)


def _boletos_limpos() -> list[Path]:
    return sorted(CORPUS_LIMPO.glob("*.pdf"))


def test_o_corpus_limpo_existe() -> None:
    """Sem corpus este arquivo passaria vazio, o que seria pior que falhar."""
    assert len(_boletos_limpos()) >= 15


@tem_tesseract
@pytest.mark.parametrize("boleto", _boletos_limpos(), ids=lambda p: p.stem)
def test_boleto_limpo_nao_e_sinalizado(boleto: Path) -> None:
    resultado = sanitiza(boleto)

    assert resultado.limpo, (
        f"falso positivo em {boleto.name}:\n{resultado.descricao()}\n"
        "Um limiar que acusa documento honesto não é conservador, é inútil."
    )


@tem_tesseract
def test_boleto_limpo_e_auto_aprovavel() -> None:
    """Ponta a ponta: documento honesto sai elegível a seguir sem revisão."""
    resultado = sanitiza(_boletos_limpos()[0])

    decisao = decide(resultado)

    assert DETECTOR_DIVERGENCIA_OCR in resultado.detectores_executados
    assert decisao.rota is Rota.AUTOMATICO


def test_detectores_offline_nao_acusam_o_corpus() -> None:
    """A parte sem OCR roda em qualquer ambiente e cobre os 15 documentos."""
    sinalizados = [
        boleto.name for boleto in _boletos_limpos() if sanitiza(boleto, com_ocr=False).achados
    ]

    assert sinalizados == []
