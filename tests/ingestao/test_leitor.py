"""Ingestão: detecção da camada de texto e escolha do caminho."""

from pathlib import Path

import pypdfium2
import pytest

from app.ingestao.documento import CaminhoDeLeitura
from app.ingestao.leitor import camada_de_texto_util, ingere, rasteriza

LIMPO = Path("dados/sinteticos/boletos/boleto-001.pdf")


@pytest.fixture(scope="module")
def digitalizado(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Um boleto rasterizado e remontado como PDF de imagem pura."""
    destino = tmp_path_factory.mktemp("digitalizados") / "digitalizado.pdf"
    pagina = pypdfium2.PdfDocument(str(LIMPO))[0]
    pagina.render(scale=150 / 72).to_pil().convert("RGB").save(destino, "PDF", resolution=150)
    return destino


class TestDeteccaoDaCamadaDeTexto:
    def test_boleto_digital_tem_camada_util(self) -> None:
        documento = ingere(LIMPO, com_ocr=False)

        assert documento.leitura is CaminhoDeLeitura.TEXTO
        assert documento.paginas_png == ()

    def test_digitalizado_nao_tem_camada_util(self, digitalizado: Path) -> None:
        documento = ingere(digitalizado, com_ocr=False)

        assert documento.leitura is CaminhoDeLeitura.VISAO
        assert len(documento.paginas_png) == 1

    def test_camada_residual_nao_conta_como_documento(self) -> None:
        """Um carimbo ou protocolo solto não é a camada de texto do boleto."""
        assert not camada_de_texto_util("protocolo 12345")
        assert not camada_de_texto_util("")

    def test_texto_de_boleto_conta(self) -> None:
        documento = ingere(LIMPO, com_ocr=False)

        assert camada_de_texto_util(documento.texto)


class TestTextoAmarradoAosAchados:
    def test_o_texto_analisado_e_o_texto_que_vai_ao_modelo(self) -> None:
        """Se fossem leituras diferentes, a defesa conferiria outro artefato."""
        documento = ingere(LIMPO, com_ocr=False)

        assert documento.texto == documento.sanitizacao.texto

    def test_documento_sem_camada_nao_teve_cobertura(self, digitalizado: Path) -> None:
        documento = ingere(digitalizado, com_ocr=False)

        assert not documento.sanitizacao_teve_cobertura
        assert documento.aviso is not None

    def test_documento_com_camada_teve_cobertura(self) -> None:
        assert ingere(LIMPO, com_ocr=False).sanitizacao_teve_cobertura


class TestRasterizacao:
    def test_produz_um_png_por_pagina(self, digitalizado: Path) -> None:
        paginas = rasteriza(digitalizado)

        assert len(paginas) == 1
        assert paginas[0].startswith(b"\x89PNG")
