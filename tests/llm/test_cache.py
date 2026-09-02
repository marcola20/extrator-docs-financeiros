"""Cache em disco: acerto, erro, invalidação e as recusas de servir lixo."""

import json
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from app.llm.cache import CacheDeExtracao, main
from app.llm.provedor import ResultadoExtracao, UsoDeTokens
from tests.llm.falso import DocumentoFalso

TEXTO = "linha digitável 34191790010104351004791020150008291070026000"
INSTRUCAO = "extraia o boleto"


def _resultado() -> ResultadoExtracao[DocumentoFalso]:
    return ResultadoExtracao(
        dados=DocumentoFalso(titulo="Boleto", valor=Decimal("1234.56")),
        provedor="falso",
        modelo="falso-1",
        uso=UsoDeTokens(entrada=900, saida=120),
        custo_estimado_usd=Decimal("0.000570"),
    )


def test_acerto_devolve_o_mesmo_dado_marcado_como_cache(tmp_path: Path) -> None:
    cache = CacheDeExtracao(diretorio=tmp_path)
    chave = cache.chave("falso", "falso-1", INSTRUCAO, TEXTO)

    assert cache.le(chave, DocumentoFalso) is None

    cache.grava(chave, _resultado())
    recuperado = cache.le(chave, DocumentoFalso)

    assert recuperado is not None
    assert recuperado.dados.titulo == "Boleto"
    # Decimal tem que voltar exato: passar por float perderia o centavo.
    assert recuperado.dados.valor == Decimal("1234.56")
    assert recuperado.custo_estimado_usd == Decimal("0.000570")
    assert recuperado.uso.entrada == 900
    assert recuperado.do_cache is True


def test_mudanca_de_prompt_muda_a_chave(tmp_path: Path) -> None:
    """Prompt novo não pode ser servido com resposta velha."""
    cache = CacheDeExtracao(diretorio=tmp_path)
    chave = cache.chave("falso", "falso-1", INSTRUCAO, TEXTO)
    cache.grava(chave, _resultado())

    outra = cache.chave("falso", "falso-1", "outro prompt", TEXTO)

    assert outra != chave
    assert cache.le(outra, DocumentoFalso) is None


def test_mudanca_de_modelo_muda_a_chave(tmp_path: Path) -> None:
    cache = CacheDeExtracao(diretorio=tmp_path)

    lite = cache.chave("gemini", "gemini-3.5-flash-lite", INSTRUCAO, TEXTO)
    flash = cache.chave("gemini", "gemini-3.8-flash", INSTRUCAO, TEXTO)

    assert lite != flash


def test_fronteira_entre_campos_nao_se_confunde(tmp_path: Path) -> None:
    """Sem o tamanho na frente, ("ab","c") e ("a","bc") colidiriam."""
    cache = CacheDeExtracao(diretorio=tmp_path)

    assert cache.chave("falso", "m", "ab", "c") != cache.chave("falso", "m", "a", "bc")


def test_arquivo_corrompido_conta_como_erro_de_cache(tmp_path: Path) -> None:
    cache = CacheDeExtracao(diretorio=tmp_path)
    chave = cache.chave("falso", "falso-1", INSTRUCAO, TEXTO)
    cache.grava(chave, _resultado())
    (tmp_path / f"{chave}.json").write_text("{isso não é json", encoding="utf-8")

    assert cache.le(chave, DocumentoFalso) is None


def test_dado_que_nao_valida_mais_no_schema_conta_como_erro(tmp_path: Path) -> None:
    """O cache é economia, nunca fonte de erro: schema mudou, entrada é ignorada."""

    class OutroSchema(BaseModel):
        obrigatorio: int

    cache = CacheDeExtracao(diretorio=tmp_path)
    chave = cache.chave("falso", "falso-1", INSTRUCAO, TEXTO)
    cache.grava(chave, _resultado())

    assert cache.le(chave, OutroSchema) is None


def test_formato_antigo_e_ignorado(tmp_path: Path) -> None:
    cache = CacheDeExtracao(diretorio=tmp_path)
    chave = cache.chave("falso", "falso-1", INSTRUCAO, TEXTO)
    cache.grava(chave, _resultado())

    caminho = tmp_path / f"{chave}.json"
    conteudo = json.loads(caminho.read_text(encoding="utf-8"))
    conteudo["versao"] = 0
    caminho.write_text(json.dumps(conteudo), encoding="utf-8")

    assert cache.le(chave, DocumentoFalso) is None


def test_cache_desligado_nao_le_nem_grava(tmp_path: Path) -> None:
    cache = CacheDeExtracao(diretorio=tmp_path, ativo=False)
    chave = cache.chave("falso", "falso-1", INSTRUCAO, TEXTO)

    cache.grava(chave, _resultado())

    assert cache.le(chave, DocumentoFalso) is None
    assert list(tmp_path.glob("*.json")) == []


def test_resultado_vindo_do_cache_nao_e_regravado(tmp_path: Path) -> None:
    cache = CacheDeExtracao(diretorio=tmp_path)
    chave = cache.chave("falso", "falso-1", INSTRUCAO, TEXTO)

    cache.grava(chave, _resultado())
    recuperado = cache.le(chave, DocumentoFalso)
    assert recuperado is not None

    outra_chave = cache.chave("falso", "falso-1", "outro", TEXTO)
    cache.grava(outra_chave, recuperado)

    assert cache.le(outra_chave, DocumentoFalso) is None


def test_limpa_apaga_todas_as_entradas(tmp_path: Path) -> None:
    cache = CacheDeExtracao(diretorio=tmp_path)
    for sufixo in ("a", "b", "c"):
        cache.grava(cache.chave("falso", "falso-1", INSTRUCAO, sufixo), _resultado())

    assert cache.limpa() == 3
    assert cache.le(cache.chave("falso", "falso-1", INSTRUCAO, "a"), DocumentoFalso) is None


def test_cli_limpar_invalida_o_cache(tmp_path: Path) -> None:
    cache = CacheDeExtracao(diretorio=tmp_path)
    cache.grava(cache.chave("falso", "falso-1", INSTRUCAO, TEXTO), _resultado())

    codigo = main(["--limpar", "--diretorio", str(tmp_path)])

    assert codigo == 0
    assert list(tmp_path.glob("*.json")) == []


def test_cli_sem_flag_nao_apaga_nada(tmp_path: Path) -> None:
    cache = CacheDeExtracao(diretorio=tmp_path)
    cache.grava(cache.chave("falso", "falso-1", INSTRUCAO, TEXTO), _resultado())

    codigo = main(["--diretorio", str(tmp_path)])

    assert codigo == 0
    assert len(list(tmp_path.glob("*.json"))) == 1
