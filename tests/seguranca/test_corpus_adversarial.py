"""O corpus adversarial versionado se comporta como o gabarito diz.

É o teste ponta a ponta da Fase 1.2: 28 documentos com ataque embutido, e
para cada um o gabarito já declara se o sanitizador deveria pegá-lo e por
quais detectores. Divergir do gabarito é falha dos dois lados — ou a defesa
regrediu, ou o gabarito está mentindo sobre o que ela faz.
"""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.seguranca.ingestao import sanitiza
from app.seguranca.politica import Rota, decide

CORPUS = Path("dados/sinteticos/boletos_adversariais")

tem_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="tesseract não instalado"
)


def _gabaritos() -> list[dict[str, Any]]:
    return [json.loads(c.read_text(encoding="utf-8")) for c in sorted(CORPUS.glob("*.json"))]


def _um_por_ataque() -> list[dict[str, Any]]:
    """Um documento de cada tipo de ataque, para o teste com OCR não custar 30s."""
    escolhidos: dict[str, dict[str, Any]] = {}
    for gabarito in _gabaritos():
        escolhidos.setdefault(gabarito["ataque"]["nome"], gabarito)
    return sorted(escolhidos.values(), key=lambda g: g["ataque"]["nome"])


def _id(gabarito: dict[str, Any]) -> str:
    return f"{gabarito['ataque']['nome']}-{gabarito['arquivo_pdf']}"


def test_o_corpus_adversarial_existe() -> None:
    gabaritos = _gabaritos()

    assert len(gabaritos) >= 25
    assert len({g["ataque"]["nome"] for g in gabaritos}) >= 6


@pytest.mark.slow
@tem_tesseract
@pytest.mark.parametrize("gabarito", _um_por_ataque(), ids=_id)
def test_deteccao_bate_com_o_gabarito(gabarito: dict[str, Any]) -> None:
    resultado = sanitiza(CORPUS / gabarito["arquivo_pdf"])

    esperado = gabarito["ataque"]["detectavel_pelo_sanitizador"]

    assert bool(resultado.achados) is esperado, (
        f"{gabarito['ataque']['nome']}: gabarito diz detectável={esperado}\n{resultado.descricao()}"
    )


@pytest.mark.slow
@tem_tesseract
@pytest.mark.parametrize("gabarito", _um_por_ataque(), ids=_id)
def test_ataque_detectavel_nunca_e_auto_aprovado(gabarito: dict[str, Any]) -> None:
    if not gabarito["ataque"]["detectavel_pelo_sanitizador"]:
        pytest.skip("este ataque é pego pela validação determinística, não aqui")

    decisao = decide(sanitiza(CORPUS / gabarito["arquivo_pdf"]))

    assert decisao.rota is Rota.REVISAO_HUMANA
    assert not decisao.auto_aprovavel


@pytest.mark.slow
@tem_tesseract
@pytest.mark.parametrize("gabarito", _um_por_ataque(), ids=_id)
def test_os_detectores_esperados_sao_os_que_acusam(gabarito: dict[str, Any]) -> None:
    """Não basta pegar: tem que pegar pelo motivo que o gabarito prevê."""
    resultado = sanitiza(CORPUS / gabarito["arquivo_pdf"])
    tipos = {a.tipo.value for a in resultado.achados}

    esperados = set(gabarito["ataque"]["detectores_esperados"])
    if "padroes" in esperados:
        assert tipos & {"padrao_de_injecao", "delimitador_falso"}
    if "texto_invisivel" in esperados:
        assert tipos & {"texto_quase_invisivel", "fonte_minuscula", "texto_fora_da_pagina"}
    if "divergencia_ocr" in esperados:
        assert "divergencia_texto_imagem" in tipos


@pytest.mark.parametrize("gabarito", _gabaritos(), ids=_id)
def test_todo_ataque_visivel_na_camada_e_pego_sem_ocr(gabarito: dict[str, Any]) -> None:
    """A parte offline da defesa, medida nos 28 documentos.

    Roda sem OCR, então é rápida e vale em qualquer ambiente. Só cobre os
    ataques cujo gabarito prevê um detector que não depende de OCR.
    """
    esperados = set(gabarito["ataque"]["detectores_esperados"])
    if not esperados - {"divergencia_ocr"}:
        pytest.skip("só o OCR pega este ataque")

    resultado = sanitiza(CORPUS / gabarito["arquivo_pdf"], com_ocr=False)

    assert resultado.achados, gabarito["ataque"]["nome"]


@pytest.mark.slow
@tem_tesseract
def test_opacidade_zero_depende_do_ocr_para_a_invisibilidade() -> None:
    """O ataque que justifica o detector (c) existir.

    `opacity: 0` não chega aos atributos do char. Neste corpus a carga usa um
    fraseado que a lista de padrões conhece, então o detector de padrões
    também acusa — mas é ele que some se o atacante reescrever a frase, e aí
    a divergência texto/imagem fica sendo a única defesa de pé.
    """
    gabarito = next(g for g in _gabaritos() if g["ataque"]["nome"] == "opacidade_zero")
    pdf = CORPUS / gabarito["arquivo_pdf"]

    com_ocr = sanitiza(pdf)
    sem_ocr = sanitiza(pdf, com_ocr=False)

    tipos_com = {a.tipo.value for a in com_ocr.achados}
    tipos_sem = {a.tipo.value for a in sem_ocr.achados}

    assert "divergencia_texto_imagem" in tipos_com
    assert "divergencia_texto_imagem" not in tipos_sem
    # Nenhum detector de texto invisível vê opacidade — é a limitação medida.
    assert not tipos_sem & {"texto_quase_invisivel", "fonte_minuscula", "texto_fora_da_pagina"}
