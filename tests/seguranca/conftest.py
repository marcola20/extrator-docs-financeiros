"""Fixtures da camada de segurança."""

from collections.abc import Callable
from pathlib import Path

import pytest
from weasyprint import HTML

MOLDE = """<html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 10mm }}
body {{ font-family: Helvetica, sans-serif; font-size: 11pt }}
.branco {{ color: #fff }}
.mini {{ font-size: 0.4pt }}
.fora {{ position: absolute; left: -500pt; top: -400pt }}
.transparente {{ opacity: 0 }}
</style></head><body>{corpo}</body></html>"""


@pytest.fixture(scope="session")
def faz_pdf(tmp_path_factory: pytest.TempPathFactory) -> Callable[[str, str], Path]:
    """Monta um PDF a partir do corpo HTML, para exercitar os detectores."""
    destino = tmp_path_factory.mktemp("pdfs")
    contador = {"n": 0}

    def constroi(corpo: str, nome: str = "documento") -> Path:
        contador["n"] += 1
        caminho = destino / f"{nome}-{contador['n']}.pdf"
        HTML(string=MOLDE.format(corpo=corpo)).write_pdf(caminho)
        return caminho

    return constroi


@pytest.fixture(scope="session")
def corpo_limpo() -> str:
    """Texto de boleto legítimo, incluindo as instruções que quase viram falso positivo."""
    return (
        "<p>Beneficiário: Comércio de Materiais Ltda</p>"
        "<p>Instruções (Texto de responsabilidade do beneficiário)</p>"
        "<p>Sr. Caixa, não receber após o vencimento.</p>"
        "<p>Após o vencimento, cobrar multa de 2% e juros de 1% ao mês.</p>"
        "<p>Pagável em qualquer banco até o vencimento.</p>"
    )
