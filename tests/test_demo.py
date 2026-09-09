"""Os casos da demonstração, e a trava que os mantém honestos.

O risco que estes testes cobrem não é de lógica, é de deriva: `app/demo.py`
promete cinco situações e `semeia_fila` processa uma lista de documentos, e nada
na linguagem obriga as duas a falarem dos mesmos arquivos. Quando elas
divergirem, a página de entrada oferecerá um link para uma decisão que não
existe — e quem descobre isso é o recrutador que abriu o link, não o CI.
"""

import ast
import sys
from pathlib import Path

import pytest

from app import demo
from app.geradores import semeia_fila


class TestCasos:
    def test_sao_os_cinco_do_enunciado(self) -> None:
        assert [caso.chave for caso in demo.CASOS] == [
            "valor_adulterado",
            "saldo_trocado",
            "instrucao_invisivel",
            "sem_cobertura",
            "limpo",
        ]

    def test_cada_caso_aponta_para_um_pdf_que_existe(self) -> None:
        """Localizar por família de ataque, e não por número, tem que funcionar."""
        for caso in demo.CASOS:
            arquivo = caso.arquivo
            assert arquivo is not None, f"{caso.chave} não achou documento no corpus"
            assert arquivo.is_file(), f"{caso.chave} aponta para {arquivo}, que não existe"

    def test_cada_caso_tem_uma_frase_que_descreve_a_situacao(self) -> None:
        """A entrada apresenta por situação; nome de arquivo não é situação."""
        for caso in demo.CASOS:
            assert caso.titulo and caso.frase
            assert ".pdf" not in caso.frase
            assert "adversarial-" not in caso.frase

    def test_nenhum_caso_repete_documento(self) -> None:
        """Cinco cartões apontando para menos de cinco documentos seria redundância."""
        arquivos = [caso.arquivo for caso in demo.CASOS]
        assert len(set(arquivos)) == len(arquivos)


class TestOSemeadorEAEntradaConcordam:
    """A trava. Ver a nota do módulo."""

    def test_todo_caso_e_um_documento_que_o_semeador_processa(self) -> None:
        boletos, informes = semeia_fila.cenarios_padrao()
        semeados = {c.pdf for c in boletos}
        for cenario in informes:
            semeados.update({cenario.anterior, cenario.atual})

        for caso in demo.CASOS:
            assert caso.arquivo in semeados, (
                f"o caso {caso.chave!r} aponta para {caso.arquivo}, que o semeador "
                f"não processa — a entrada ofereceria um link para uma decisão "
                f"inexistente"
            )

    def test_o_par_do_saldo_trocado_entra_inteiro(self) -> None:
        """O cruzamento entre anos precisa dos dois documentos, não de um."""
        atacado = demo.por_familia_de_ataque(
            demo.INFORMES_ADVERSARIAIS, "saldo_anterior_adulterado"
        )
        assert atacado is not None
        anterior, atual = demo.par_de(atacado)

        _, informes = semeia_fila.cenarios_padrao()
        assert any(c.anterior == anterior and c.atual == atual for c in informes)


class TestLocalizadores:
    def test_par_de_devolve_ano_anterior_primeiro(self) -> None:
        """Inverter a ordem compararia saldos que não têm por que bater."""
        atual = demo.por_layout(demo.INFORMES, "instituicao_financeira", papel="ano")
        assert atual is not None

        anterior, encontrado = demo.par_de(atual)

        assert encontrado == atual
        assert anterior != atual
        # E o inverso: partindo do documento do ano anterior, a ordem é a mesma.
        assert demo.par_de(anterior) == (anterior, atual)

    def test_familia_inexistente_devolve_nada(self) -> None:
        """`None`, e não exceção: a entrada mostra o caso como indisponível."""
        assert demo.por_familia_de_ataque(demo.BOLETOS_ADVERSARIAIS, "nao_existe") is None

    def test_diretorio_inexistente_devolve_nada(self) -> None:
        assert demo.por_layout(Path("dados/sinteticos/nao-existe"), "fonte_pagadora") is None


class TestNaoImportaOPipeline:
    """A API importa este módulo, e a API não carrega o pipeline."""

    def test_o_modulo_so_importa_a_biblioteca_padrao(self) -> None:
        """Confere os imports, e não o texto: o docstring cita `pdfplumber`."""
        arvore = ast.parse(Path("app/demo.py").read_text(encoding="utf-8"))

        importados: set[str] = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                importados.update(alias.name.split(".")[0] for alias in no.names)
            elif isinstance(no, ast.ImportFrom) and no.module:
                importados.add(no.module.split(".")[0])

        assert importados <= set(sys.stdlib_module_names), (
            f"app/demo.py importa {sorted(importados - set(sys.stdlib_module_names))}. "
            f"A API importa este módulo, e uma dependência aqui entra no processo "
            f"que existe para não carregar o pipeline (ver o Dockerfile)"
        )


@pytest.mark.parametrize("caso", demo.CASOS, ids=lambda c: c.chave)
def test_o_gabarito_do_caso_esta_ao_lado_do_pdf(caso: demo.Caso) -> None:
    """Sem o gabarito, o provedor do semeador não sabe o que devolver."""
    arquivo = caso.arquivo
    assert arquivo is not None
    assert arquivo.with_suffix(".json").is_file()
