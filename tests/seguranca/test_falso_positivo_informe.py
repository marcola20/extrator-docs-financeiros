"""Taxa de falso positivo do sanitizador no corpus limpo de informes.

Companheiro de `test_falso_positivo.py`, que faz o mesmo com boletos. Os dois
existem juntos de propósito: os limiares foram calibrados contra boletos, e o
informe é outro documento — rodapé legal miúdo, tabelas com fundo zebrado,
faixa escura com texto branco, rótulos de campo em maiúsculas de 5,5pt.

Quando este arquivo nasceu, **os 24 informes limpos eram sinalizados**, por
três causas independentes que o corpus de boleto não tinha como expor:

1. `texto_quase_invisivel` acusava char preto por estar sobre retângulo claro
   — a regra olhava só a cor do texto e a presença de um retângulo, nunca a
   distância entre as duas;
2. o mesmo detector acusava texto branco na faixa azul escura, por assumir a
   página branca;
3. `dispensa_de_validacao` casava com "não tem validade fiscal" do rodapé.

Nenhuma delas se resolvia mexendo em número. Ver ADR 008.
"""

import json
import shutil
from pathlib import Path

import pytest

from app.seguranca.ingestao import DETECTOR_DIVERGENCIA_OCR, sanitiza
from app.seguranca.politica import Rota, decide

CORPUS_INFORMES = Path("dados/sinteticos/informes")

tem_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="tesseract não instalado; a divergência texto/imagem não roda",
)


def _informes_limpos() -> list[Path]:
    return sorted(CORPUS_INFORMES.glob("*.pdf"))


def test_o_corpus_limpo_existe() -> None:
    """Sem corpus este arquivo passaria vazio, o que seria pior que falhar."""
    assert len(_informes_limpos()) >= 24


def test_detectores_offline_nao_acusam_o_corpus() -> None:
    """A parte sem OCR roda em qualquer ambiente e cobre os 24 documentos."""
    sinalizados = [
        informe.name for informe in _informes_limpos() if sanitiza(informe, com_ocr=False).achados
    ]

    assert sinalizados == []


def test_o_rodape_legal_nao_e_lido_como_injecao() -> None:
    """ "não tem validade fiscal" é prosa de rodapé, não pedido de dispensa.

    O mesmo vale para "sem validade sem autenticação mecânica", que todo
    comprovante bancário real imprime. Afrouxar o padrão inteiro para calar
    isto cegaria o detector; a exceção é só para `validade`, o substantivo.
    """
    achados = [
        achado
        for informe in _informes_limpos()
        for achado in sanitiza(informe, com_ocr=False).achados
        if "validacao" in achado.detalhe or "validação" in achado.detalhe
    ]

    assert achados == []


@pytest.mark.slow
@tem_tesseract
@pytest.mark.parametrize("informe", _informes_limpos(), ids=lambda p: p.stem)
def test_informe_limpo_nao_e_sinalizado(informe: Path) -> None:
    resultado = sanitiza(informe)

    assert resultado.limpo, (
        f"falso positivo em {informe.name}:\n{resultado.descricao()}\n"
        "Um limiar que acusa documento honesto não é conservador, é inútil."
    )


@pytest.mark.slow
@tem_tesseract
def test_informe_limpo_e_auto_aprovavel() -> None:
    """Ponta a ponta: documento honesto sai elegível a seguir sem revisão."""
    resultado = sanitiza(_informes_limpos()[0])

    decisao = decide(resultado)

    assert DETECTOR_DIVERGENCIA_OCR in resultado.detectores_executados
    assert decisao.rota is Rota.AUTOMATICO


@pytest.mark.slow
@tem_tesseract
def test_os_dois_layouts_passam_limpos() -> None:
    """Um corpus em que só um layout passa não teria medido o outro."""
    por_layout: dict[str, int] = {}
    for informe in _informes_limpos():
        gabarito = json.loads(informe.with_suffix(".json").read_text(encoding="utf-8"))
        if sanitiza(informe).limpo:
            por_layout[gabarito["layout"]] = por_layout.get(gabarito["layout"], 0) + 1

    assert por_layout.get("fonte_pagadora", 0) >= 12
    assert por_layout.get("instituicao_financeira", 0) >= 12
