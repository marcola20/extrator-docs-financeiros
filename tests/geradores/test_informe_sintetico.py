"""Gerador de informes: round-trip, reprodutibilidade e o corpus que ele produz.

O teste que carrega o peso é o do par: se os saldos não fecharem entre os dois
anos, a validação mais forte da fase não tem como ser exercitada, e um corpus
que não exercita o sinal deixa o sinal sem cobertura sem que nada acuse.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.dominio.cruzamento import cruza
from app.dominio.informe import Informe, Layout
from app.geradores import informe_sintetico
from app.geradores.boleto_sintetico import formata_moeda
from app.geradores.informe_sintetico import gera_pares, lote_existente, salva

CORPUS = Path("dados/sinteticos/informes")
REFERENCIA = date(2026, 9, 4)


@pytest.fixture(scope="module")
def pares() -> list[tuple[informe_sintetico.InformeSintetico, informe_sintetico.InformeSintetico]]:
    return gera_pares(8, semente=2026, hoje=REFERENCIA)


class TestParDeAnosConsecutivos:
    def test_todo_par_cruza_e_fecha(
        self, pares: list[tuple[informe_sintetico.InformeSintetico, ...]]
    ) -> None:
        for anterior, atual in pares:
            resultado = cruza(atual.informe, anterior.informe)

            assert resultado.comparavel, f"{atual.par}: {resultado.descricao()}"
            assert resultado.valido, f"{atual.par}: {resultado.descricao()}"

    def test_o_par_e_do_mesmo_titular_e_da_mesma_fonte(
        self, pares: list[tuple[informe_sintetico.InformeSintetico, ...]]
    ) -> None:
        for anterior, atual in pares:
            assert atual.informe.beneficiario_cpf == anterior.informe.beneficiario_cpf
            assert atual.informe.fonte_pagadora_cnpj == anterior.informe.fonte_pagadora_cnpj

    def test_os_anos_sao_consecutivos(
        self, pares: list[tuple[informe_sintetico.InformeSintetico, ...]]
    ) -> None:
        for anterior, atual in pares:
            assert atual.informe.ano_calendario == anterior.informe.ano_calendario + 1

    def test_o_saldo_do_ano_anterior_e_o_saldo_declarado_no_ano_anterior(
        self, pares: list[tuple[informe_sintetico.InformeSintetico, ...]]
    ) -> None:
        """O encadeamento explícito, sem passar pelo validador que o confere."""
        bancarios = [(a, b) for a, b in pares if b.informe.layout is Layout.INSTITUICAO_FINANCEIRA]
        assert bancarios, "o lote precisa ter par bancário para isto significar algo"

        for anterior, atual in bancarios:
            de_antes = {s.especificacao: s.saldo_31_12 for s in anterior.informe.saldos}
            for saldo in atual.informe.saldos:
                if saldo.especificacao in de_antes:
                    assert saldo.saldo_31_12_anterior == de_antes[saldo.especificacao]

    def test_o_cruzamento_do_layout_de_fonte_pagadora_fica_sem_cobertura(
        self, pares: list[tuple[informe_sintetico.InformeSintetico, ...]]
    ) -> None:
        """Não é falha: o documento não tem saldo. Tem que aparecer como tal."""
        salariais = [(a, b) for a, b in pares if b.informe.layout is Layout.FONTE_PAGADORA]
        assert salariais

        for anterior, atual in salariais:
            resultado = cruza(atual.informe, anterior.informe)

            assert resultado.comparavel
            assert not resultado.tem_cobertura


class TestOsDoisLayouts:
    def test_o_lote_tem_os_dois(
        self, pares: list[tuple[informe_sintetico.InformeSintetico, ...]]
    ) -> None:
        layouts = {atual.informe.layout for _, atual in pares}

        assert layouts == {Layout.FONTE_PAGADORA, Layout.INSTITUICAO_FINANCEIRA}

    def test_fonte_pagadora_nao_imprime_total_em_quadro_nenhum(
        self, pares: list[tuple[informe_sintetico.InformeSintetico, ...]]
    ) -> None:
        """É o que o modelo oficial faz, e é o que deixa esses quadros sem cobertura."""
        for _, atual in pares:
            if atual.informe.layout is not Layout.FONTE_PAGADORA:
                continue
            assert all(quadro.total_impresso is None for quadro in atual.informe.quadros)
            assert len(atual.informe.quadros_sem_cobertura) == 3

    def test_layout_bancario_imprime_total_e_fecha(
        self, pares: list[tuple[informe_sintetico.InformeSintetico, ...]]
    ) -> None:
        for _, atual in pares:
            if atual.informe.layout is not Layout.INSTITUICAO_FINANCEIRA:
                continue
            assert atual.informe.quadros_sem_cobertura == ()
            for conferencia in atual.informe.conferencias():
                assert conferencia.tem_cobertura
                assert not conferencia.divergiu

    def test_so_o_bancario_tem_saldo(
        self, pares: list[tuple[informe_sintetico.InformeSintetico, ...]]
    ) -> None:
        for _, atual in pares:
            tem_saldo = bool(atual.informe.saldos)
            assert tem_saldo == (atual.informe.layout is Layout.INSTITUICAO_FINANCEIRA)


class TestVariacaoDosQuadros:
    def test_o_lote_tem_quadro_vazio_e_quadro_longo(self) -> None:
        """As duas pontas que a Fase 2.2 precisa aguentar: lista vazia e quebra de página."""
        pares = gera_pares(12, semente=2026, hoje=REFERENCIA)
        tamanhos = [
            len(quadro.linhas)
            for par in pares
            for sintetico in par
            for quadro in sintetico.informe.quadros
        ]

        assert 0 in tamanhos, "nenhum quadro vazio no lote"
        assert max(tamanhos) >= 40, f"o quadro mais longo tem {max(tamanhos)} linhas"


class TestReprodutibilidade:
    def test_mesma_semente_e_mesma_data_dao_o_mesmo_lote(self) -> None:
        um = gera_pares(4, semente=7, hoje=REFERENCIA)
        outro = gera_pares(4, semente=7, hoje=REFERENCIA)

        assert [s.informe for par in um for s in par] == [s.informe for par in outro for s in par]

    def test_data_diferente_muda_o_lote(self) -> None:
        """O ano-calendário sai da data; só a semente não reproduz nada."""
        um = gera_pares(2, semente=7, hoje=REFERENCIA)
        outro = gera_pares(2, semente=7, hoje=date(2025, 9, 4))

        assert um[0][1].informe.ano_calendario != outro[0][1].informe.ano_calendario

    def test_a_procedencia_vai_no_gabarito(self, tmp_path: Path) -> None:
        _, atual = gera_pares(1, semente=7, hoje=REFERENCIA)[0]

        _, caminho_json = salva(atual, tmp_path, "informe-002", "informe-001.pdf")

        gabarito = json.loads(caminho_json.read_text(encoding="utf-8"))
        assert gabarito["gerado_com"] == {
            "semente": 7,
            "data_de_referencia": "2026-09-04",
        }

    def test_semente_diferente_muda_o_lote(self) -> None:
        um = gera_pares(2, semente=7, hoje=REFERENCIA)
        outro = gera_pares(2, semente=8, hoje=REFERENCIA)

        assert um[0][1].informe != outro[0][1].informe


class TestRoundTrip:
    def test_o_gabarito_volta_a_ser_um_informe_valido(self, tmp_path: Path) -> None:
        _, atual = gera_pares(1, semente=11, hoje=REFERENCIA)[0]

        _, caminho_json = salva(atual, tmp_path, "informe-002", "informe-001.pdf")

        gabarito = json.loads(caminho_json.read_text(encoding="utf-8"))
        assert Informe.model_validate(gabarito["campos"]) == atual.informe

    def test_o_gabarito_aponta_para_o_par(self, tmp_path: Path) -> None:
        """Sem isto o eval teria que adivinhar quem cruza com quem."""
        anterior, atual = gera_pares(1, semente=11, hoje=REFERENCIA)[0]

        salva(anterior, tmp_path, "informe-001", "informe-002.pdf")
        _, caminho_json = salva(atual, tmp_path, "informe-002", "informe-001.pdf")

        gabarito = json.loads(caminho_json.read_text(encoding="utf-8"))
        assert gabarito["par"]["arquivo_do_par"] == "informe-001.pdf"
        assert gabarito["par"]["papel"] == "ano"

    def test_o_pdf_sai_com_texto_extraivel(self, tmp_path: Path) -> None:
        pdfplumber = pytest.importorskip("pdfplumber")
        _, atual = gera_pares(1, semente=11, hoje=REFERENCIA)[0]

        caminho_pdf, _ = salva(atual, tmp_path, "informe-002", "informe-001.pdf")

        with pdfplumber.open(caminho_pdf) as pdf:
            texto = "\n".join(pagina.extract_text() or "" for pagina in pdf.pages)
        assert atual.informe.beneficiario_nome in texto
        assert str(atual.informe.ano_calendario) in texto

    def test_valores_saem_impressos_no_padrao_brasileiro(self, tmp_path: Path) -> None:
        pdfplumber = pytest.importorskip("pdfplumber")
        _, atual = gera_pares(1, semente=11, hoje=REFERENCIA)[0]
        linhas = [linha for quadro in atual.informe.quadros for linha in quadro.linhas]
        assert linhas, "o informe precisa ter linha para isto significar algo"

        caminho_pdf, _ = salva(atual, tmp_path, "informe-002", "informe-001.pdf")

        with pdfplumber.open(caminho_pdf) as pdf:
            texto = "\n".join(pagina.extract_text() or "" for pagina in pdf.pages)
        esperado = formata_moeda(linhas[0].valor)
        assert esperado in texto


class TestLoteExistente:
    def test_diretorio_vazio_nao_tem_lote(self, tmp_path: Path) -> None:
        assert lote_existente(tmp_path, "informe") == []

    def test_lote_gravado_e_detectado(self, tmp_path: Path) -> None:
        _, atual = gera_pares(1, semente=11, hoje=REFERENCIA)[0]
        salva(atual, tmp_path, "informe-001", "informe-002.pdf")

        assert len(lote_existente(tmp_path, "informe")) == 2

    def test_a_cli_recusa_sobrescrever_sem_forcar(self, tmp_path: Path) -> None:
        """Gerar por cima trocaria o corpus e invalidaria os evals anteriores."""
        _, atual = gera_pares(1, semente=11, hoje=REFERENCIA)[0]
        salva(atual, tmp_path, "informe-001", "informe-002.pdf")

        codigo = informe_sintetico.main(["--pares", "1", "--saida", str(tmp_path)])

        assert codigo == 1


class TestCorpusVersionado:
    """O corpus no repositório precisa continuar coerente com o código."""

    def test_o_corpus_existe(self) -> None:
        assert len(sorted(CORPUS.glob("*.pdf"))) >= 24

    def test_todo_gabarito_do_corpus_e_um_informe_valido(self) -> None:
        for caminho in sorted(CORPUS.glob("*.json")):
            dados = json.loads(caminho.read_text(encoding="utf-8"))
            Informe.model_validate(dados["campos"])

    def test_todo_par_do_corpus_cruza_e_fecha(self) -> None:
        gabaritos = {
            caminho.name: json.loads(caminho.read_text(encoding="utf-8"))
            for caminho in sorted(CORPUS.glob("*.json"))
        }
        pares_conferidos = 0
        for nome, dados in gabaritos.items():
            if dados["par"]["papel"] != "ano":
                continue
            par = dados["par"]["arquivo_do_par"].replace(".pdf", ".json")
            resultado = cruza(
                Informe.model_validate(dados["campos"]),
                Informe.model_validate(gabaritos[par]["campos"]),
            )
            assert resultado.valido, f"{nome}: {resultado.descricao()}"
            pares_conferidos += 1

        assert pares_conferidos >= 12

    def test_o_corpus_tem_par_bancario_com_cobertura_de_verdade(self) -> None:
        """Um corpus só de fonte pagadora deixaria o cruzamento sem exercício."""
        gabaritos = {
            caminho.name: json.loads(caminho.read_text(encoding="utf-8"))
            for caminho in sorted(CORPUS.glob("*.json"))
        }
        com_cobertura = 0
        for dados in gabaritos.values():
            if dados["par"]["papel"] != "ano":
                continue
            par = dados["par"]["arquivo_do_par"].replace(".pdf", ".json")
            resultado = cruza(
                Informe.model_validate(dados["campos"]),
                Informe.model_validate(gabaritos[par]["campos"]),
            )
            com_cobertura += int(resultado.tem_cobertura)

        assert com_cobertura >= 6

    def test_os_valores_do_corpus_sao_decimal(self) -> None:
        """Valor monetário nunca vira float, nem passando por JSON."""
        dados = json.loads(sorted(CORPUS.glob("*.json"))[0].read_text(encoding="utf-8"))
        informe = Informe.model_validate(dados["campos"])

        for quadro in informe.quadros:
            for linha in quadro.linhas:
                assert isinstance(linha.valor, Decimal)
