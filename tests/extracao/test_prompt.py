"""Prompt versionado em arquivo."""

from pathlib import Path

import pytest

from app.extracao import prompt as modulo


class TestCarregamento:
    def test_le_nome_e_versao_do_cabecalho(self) -> None:
        prompt = modulo.carrega()

        assert prompt.nome == "boleto"
        assert prompt.versao >= 1
        assert prompt.texto

    def test_o_prompt_fica_em_arquivo_e_nao_no_codigo(self) -> None:
        """O eval precisa dizer qual versão produziu qual resultado."""
        assert (modulo.DIRETORIO_PROMPTS / modulo.PROMPT_BOLETO).is_file()

    def test_identificador_junta_versao_e_hash(self) -> None:
        """O hash pega edição que esqueceu de subir a versão."""
        prompt = modulo.carrega()

        assert prompt.identificador.startswith(f"{prompt.nome}-v{prompt.versao}+")
        assert len(prompt.identificador.split("+")[1]) == 8

    def test_editar_o_texto_muda_o_identificador(self, tmp_path: Path) -> None:
        original = (modulo.DIRETORIO_PROMPTS / modulo.PROMPT_BOLETO).read_text("utf-8")
        alterado = modulo.DIRETORIO_PROMPTS / "__teste.md"
        alterado.write_text(original + "\numa linha a mais\n", encoding="utf-8")
        try:
            assert modulo.carrega("__teste.md").digest != modulo.carrega().digest
        finally:
            alterado.unlink()

    def test_arquivo_sem_cabecalho_e_erro(self) -> None:
        sem = modulo.DIRETORIO_PROMPTS / "__sem_cabecalho.md"
        sem.write_text("só o corpo\n", encoding="utf-8")
        try:
            with pytest.raises(ValueError, match="cabeçalho"):
                modulo.carrega("__sem_cabecalho.md")
        finally:
            sem.unlink()


class TestConteudo:
    def test_manda_copiar_e_nao_converter(self) -> None:
        """O grounding depende de o modelo copiar o que está impresso."""
        texto = modulo.carrega().texto.lower()

        assert "não converta" in texto or "nao converta" in texto

    def test_avisa_sobre_instrucao_embutida_no_documento(self) -> None:
        texto = modulo.carrega().texto.lower()

        assert "ignorar instruções" in texto or "ordem dirigida" in texto
