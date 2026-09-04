"""Corpus adversarial de informes: cada ataque é barrado por quem o gabarito diz.

O teste central não é "o ataque é pego", é **"é pego por quem devia"**. Um
ataque de aritmética que só o sanitizador acusa passaria despercebido num
corpus com outro layout, e um buraco de cobertura que ninguém declara vira
armadilha silenciosa.

Por isso o gabarito carrega `sinal_esperado`, e um dos valores possíveis é
`nenhum` — o caso, medido e declarado, da linha injetada num quadro que não
imprime total.
"""

import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.dominio.cruzamento import cruza
from app.dominio.informe import Informe, Layout
from app.geradores import informe_adversarial
from app.geradores.informe_adversarial import (
    ATAQUES_DE_QUALQUER_LAYOUT,
    ATAQUES_SO_DE_INSTITUICAO_FINANCEIRA,
    gera_lote,
)
from app.seguranca.ingestao import sanitiza

CORPUS = Path("dados/sinteticos/informes_adversariais")
REFERENCIA = date(2026, 9, 4)


def _gabaritos() -> dict[str, dict[str, Any]]:
    return {
        caminho.stem: json.loads(caminho.read_text(encoding="utf-8"))
        for caminho in sorted(CORPUS.glob("*.json"))
    }


def _com_ataque() -> list[tuple[str, dict[str, Any]]]:
    return [(nome, g) for nome, g in _gabaritos().items() if "ataque" in g]


def _sinais_que_pegaram(nome: str, gabarito: dict[str, Any], gabaritos: dict[str, Any]) -> set[str]:
    """Quais dos três sinais determinísticos barram este documento."""
    pego: set[str] = set()
    if not sanitiza(CORPUS / f"{nome}.pdf", com_ocr=False).limpo:
        pego.add("sanitizador")
    try:
        informe = Informe.model_validate(gabarito["campos"])
    except ValidationError:
        pego.add("aritmetica")
        return pego
    if gabarito["par"]["papel"] == "ano":
        par = Path(gabarito["par"]["arquivo_do_par"]).stem
        try:
            outro = Informe.model_validate(gabaritos[par]["campos"])
        except ValidationError:
            return pego
        if not cruza(informe, outro).valido:
            pego.add("cruzamento")
    return pego


class TestCorpusVersionado:
    def test_o_corpus_existe(self) -> None:
        assert len(sorted(CORPUS.glob("*.pdf"))) >= 32

    def test_toda_familia_de_ataque_aparece(self) -> None:
        """Família ausente é cobertura que o corpus não mede e ninguém percebe."""
        familias = {g["ataque"]["nome"] for _, g in _com_ataque()}
        esperadas = {
            f.__name__ for f in ATAQUES_DE_QUALQUER_LAYOUT + ATAQUES_SO_DE_INSTITUICAO_FINANCEIRA
        }

        assert familias == esperadas

    def test_o_ataque_que_so_o_cruzamento_ve_esta_no_corpus(self) -> None:
        """É a razão de a fase ter validação cruzada; sem ele nada a exercita."""
        familias = Counter(g["ataque"]["nome"] for _, g in _com_ataque())

        assert familias["saldo_anterior_adulterado"] >= 1

    def test_os_dois_layouts_sao_atacados(self) -> None:
        layouts = {g["layout"] for _, g in _com_ataque()}

        assert layouts == {Layout.FONTE_PAGADORA.value, Layout.INSTITUICAO_FINANCEIRA.value}

    @pytest.mark.parametrize(
        ("nome", "gabarito"), _com_ataque(), ids=[nome for nome, _ in _com_ataque()]
    )
    def test_cada_ataque_e_barrado_por_quem_o_gabarito_declara(
        self, nome: str, gabarito: dict[str, Any]
    ) -> None:
        esperado = gabarito["sinal_esperado"]
        pego = _sinais_que_pegaram(nome, gabarito, _gabaritos())

        if esperado == "nenhum":
            assert pego == set(), (
                f"{nome}: o gabarito declara que nenhum sinal pega este ataque, "
                f"mas {sorted(pego)} pegou. Se a cobertura melhorou, o gabarito "
                f"precisa ser atualizado — o corpus não pode mentir para menos."
            )
        else:
            assert esperado in pego, (
                f"{nome}: esperado ser barrado por {esperado!r}, barrado por "
                f"{sorted(pego) or 'ninguém'}"
            )

    def test_o_buraco_de_cobertura_esta_declarado_e_e_o_conhecido(self) -> None:
        """O único ataque que nada pega, e o motivo.

        Linha injetada num quadro sem total impresso: não há soma que deixe de
        fechar, e a página não tem defeito visual. É consequência direta de o
        comprovante de fonte pagadora não imprimir total (ADR 007), e está no
        corpus para que a Fase 2.3 meça o buraco em vez de supô-lo coberto.
        """
        sem_cobertura = [
            (nome, g["ataque"]["nome"], g["layout"])
            for nome, g in _com_ataque()
            if g["sinal_esperado"] == "nenhum"
        ]

        assert sem_cobertura, "o corpus perdeu o caso sem cobertura"
        for _, familia, layout in sem_cobertura:
            assert familia == "linha_injetada"
            assert layout == Layout.FONTE_PAGADORA.value


class TestGabaritoSegueOAdr006:
    def test_campos_guarda_o_impresso_e_dado_verdadeiro_o_valido(self) -> None:
        aritmeticos = [
            (nome, g)
            for nome, g in _com_ataque()
            if g["ataque"]["nome"] in ("linha_injetada", "total_adulterado", "quadro_duplicado")
        ]
        assert aritmeticos

        for nome, gabarito in aritmeticos:
            assert gabarito["campos"] != gabarito["dado_verdadeiro"], nome
            Informe.model_validate(gabarito["dado_verdadeiro"])

    def test_ataque_sem_adulteracao_imprime_o_gabarito(self) -> None:
        """Injeção textual não mexe nos campos; o que muda é só a página."""
        textuais = [
            (nome, g)
            for nome, g in _com_ataque()
            if g["ataque"]["nome"].startswith("instrucao_")
            or g["ataque"]["nome"] == "delimitador_falso"
        ]
        assert textuais

        for nome, gabarito in textuais:
            assert gabarito["campos"] == gabarito["dado_verdadeiro"], nome


class TestGeracao:
    def test_mesma_semente_da_o_mesmo_lote(self) -> None:
        um = gera_lote(4, semente=3, hoje=REFERENCIA)
        outro = gera_lote(4, semente=3, hoje=REFERENCIA)

        assert [a.ataque.nome for a in um] == [a.ataque.nome for a in outro]

    def test_o_par_do_documento_atacado_continua_integro(self) -> None:
        """O ataque mora num dos dois; o outro é o documento honesto que o denuncia."""
        for adversarial in gera_lote(6, semente=3, hoje=REFERENCIA):
            intacto = adversarial.anterior if adversarial.alvo == "atual" else adversarial.atual
            assert intacto.informe.layout in (
                Layout.FONTE_PAGADORA,
                Layout.INSTITUICAO_FINANCEIRA,
            )

    def test_lote_pequeno_ainda_traz_o_ataque_exclusivo(self) -> None:
        """A roda começa pelo exclusivo; antes disso ele sumia em lote pequeno."""
        nomes = {a.ataque.nome for a in gera_lote(4, semente=3, hoje=REFERENCIA)}

        assert "saldo_anterior_adulterado" in nomes

    def test_a_cli_recusa_sobrescrever_sem_forcar(self, tmp_path: Path) -> None:
        assert informe_adversarial.main(["--pares", "1", "--saida", str(tmp_path)]) == 0
        assert informe_adversarial.main(["--pares", "1", "--saida", str(tmp_path)]) == 1
