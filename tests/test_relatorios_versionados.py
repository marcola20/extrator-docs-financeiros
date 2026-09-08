"""Trava sobre o que um relatório de eval pode carregar para o repositório.

`resultados/` passou a ser versionado: os números são resultado do projeto, o
README os cita e linka o JSON de onde cada um saiu, e sem o arquivo no
repositório esses links quebram para quem clona. A decisão está escrita no
`.gitignore`.

Ela vem com uma condição, e é esta trava que a mantém verdadeira: **o relatório
não carrega valor extraído nenhum.** Ele guarda taxas, contagens, booleanos por
campo, nomes de arquivo do corpus sintético e a procedência do lote. `campos_certos`
é booleano — "o modelo acertou este campo?" —, e não o texto que o modelo
devolveu.

A diferença importa mesmo com corpus sintético, porque o dia em que o pipeline
rodar sobre documento real é o dia em que o relatório passaria a carregar
conteúdo de documento para dentro do git. Guardar o que o modelo escreveu é uma
mudança tentadora — ajuda a depurar um escape —, e sem esta trava ela entraria
sem ninguém notar que mudou o que sobe para o repositório.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[1]
RESULTADOS = RAIZ / "resultados"

# Chaves que guardam texto livre. Toda outra é número, booleano ou lista deles,
# e a trava confere isso separadamente.
TEXTO_ESPERADO = frozenset(
    {
        "prompt",
        "modelo",
        "provedor",
        "auto_consistencia",
        "data",
        "documento",
        "ataque",
        "sinal_esperado",
        "erro",
        "tipo_de_erro",
        "tipo",
        "layout",
        "par",
        "nome",
        "retomada_de",
        "data_de_referencia",
        "custo_total_usd",
        "custo_por_documento_usd",
        "custo_usd",
        # Listas de **nome**, nunca de valor: nome de arquivo do corpus, nome
        # de campo, nome de sinal. `test_as_listas_de_nome_so_tem_nome` é o que
        # mantém isso verdadeiro — declarar aqui sozinho não bastaria.
        "escapes",
        "falhas",
        "nao_tentados",
        "ataques_que_venceram",
        "documentos_so_por_consistencia",
        "documentos_so_por_falta_de_cobertura",
        "documentos_auto_aprovados_sem_cobertura",
        "adversariais_que_alteraram_a_saida",
        "sinais_que_barraram",
        # Quais campos divergiram do gabarito — os nomes deles, não o que o
        # modelo escreveu neles. É a distinção que esta trava inteira defende.
        "campos",
    }
)

ARQUIVO = re.compile(r"^(boleto|adversarial|informe)-\d+\.pdf$")
"""Nome de documento do corpus sintético. Documento real nunca chega aqui."""

NOMES_DE_LISTA = {
    "escapes": ARQUIVO,
    "falhas": ARQUIVO,
    "nao_tentados": ARQUIVO,
    "ataques_que_venceram": ARQUIVO,
    "documentos_so_por_consistencia": ARQUIVO,
    "documentos_so_por_falta_de_cobertura": ARQUIVO,
    "documentos_auto_aprovados_sem_cobertura": ARQUIVO,
    "adversariais_que_alteraram_a_saida": ARQUIVO,
    "campos": re.compile(r"^[a-z][a-z0-9_]*$"),
    "sinais_que_barraram": re.compile(r"^[a-z][a-z0-9_]*$"),
}
"""A forma que cada lista de nome tem de ter.

Existe porque declarar a chave em `TEXTO_ESPERADO` só diz "esta chave guarda
texto"; o que importa é **qual** texto. Um `escapes` que passasse a guardar o
valor extraído em vez do nome do arquivo continuaria sendo uma lista de strings
numa chave declarada, e passaria batido sem esta forma.
"""

# O que não pode aparecer em texto nenhum do relatório.
SEGREDO = re.compile(
    r"(AIza[0-9A-Za-z_\-]{10,}|sk-ant-|/home/|/mnt/|[A-Za-z]:\\\\"
    r"|api[_-]?key\s*[:=]|password\s*[:=]|@[a-z0-9.-]+\.(com|br|org|net)\b)",
    re.IGNORECASE,
)

_EM_REPOSITORIO = (
    subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=RAIZ,
        capture_output=True,
        check=False,
    ).returncode
    == 0
)

exige_repositorio = pytest.mark.skipif(
    not _EM_REPOSITORIO, reason="fora de um repositório git não há índice para conferir"
)


def _relatorios() -> list[Path]:
    return sorted(RESULTADOS.glob("eval-*.json"))


def _textos(objeto: Any, caminho: str = "") -> list[tuple[str, str]]:
    """Todo texto do relatório, com o caminho da chave onde ele está."""
    if isinstance(objeto, dict):
        return [
            par
            for chave, valor in objeto.items()
            for par in _textos(valor, f"{caminho}.{chave}" if caminho else chave)
        ]
    if isinstance(objeto, list):
        return [par for item in objeto for par in _textos(item, f"{caminho}[]")]
    if isinstance(objeto, str):
        return [(caminho, objeto)]
    return []


def test_existe_relatorio_versionado() -> None:
    """Sem relatório este arquivo passaria vazio, o que seria pior que falhar."""
    assert _relatorios(), "resultados/ está vazio; o README linka esses arquivos"


@exige_repositorio
def test_os_relatorios_estao_no_git() -> None:
    """O README linka os JSONs; fora do git os links quebram para quem clona."""
    versionados = subprocess.run(
        ["git", "ls-files", "resultados/"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    faltando = [r.name for r in _relatorios() if f"resultados/{r.name}" not in versionados]

    assert not faltando, f"relatório fora do git: {', '.join(faltando)}"


@pytest.mark.parametrize("relatorio", _relatorios(), ids=lambda p: p.stem)
def test_nenhuma_chave_de_texto_inesperada(relatorio: Path) -> None:
    """Chave de texto nova é onde um valor extraído entraria sem alarme.

    A lista não é decoração: `campos_certos` guarda booleano de propósito, e
    trocá-lo pelo que o modelo escreveu é a mudança que esta trava existe para
    obrigar a discutir. Se a chave nova for legítima, declare-a aqui — e ao
    declará-la, confira que ela não carrega conteúdo de documento.
    """
    dados = json.loads(relatorio.read_text(encoding="utf-8"))

    inesperadas = sorted(
        {
            caminho.split(".")[-1].removesuffix("[]")
            for caminho, _ in _textos(dados)
            if caminho.split(".")[-1].removesuffix("[]") not in TEXTO_ESPERADO
        }
    )

    assert not inesperadas, (
        f"{relatorio.name} tem chave de texto não declarada: {', '.join(inesperadas)}. "
        f"Confira que ela não carrega valor extraído antes de declará-la em TEXTO_ESPERADO."
    )


@pytest.mark.parametrize("relatorio", _relatorios(), ids=lambda p: p.stem)
def test_as_listas_de_nome_so_tem_nome(relatorio: Path) -> None:
    """Declarar a chave diz que ela guarda texto; isto diz **qual** texto.

    Um `escapes` que passasse a guardar o valor extraído em vez do nome do
    arquivo continuaria sendo lista de strings numa chave declarada.
    """
    dados = json.loads(relatorio.read_text(encoding="utf-8"))

    fora_de_forma = [
        f"{caminho}: {texto!r}"
        for caminho, texto in _textos(dados)
        if (forma := NOMES_DE_LISTA.get(caminho.split(".")[-1].removesuffix("[]")))
        and not forma.match(texto)
    ]

    assert not fora_de_forma, (
        f"{relatorio.name} tem lista de nome com conteúdo que não é nome: {fora_de_forma}"
    )


@pytest.mark.parametrize("relatorio", _relatorios(), ids=lambda p: p.stem)
def test_nao_carrega_segredo_nem_caminho_absoluto(relatorio: Path) -> None:
    """Mensagem de erro do provedor é o texto mais livre que o relatório guarda."""
    achados = [
        f"{caminho}: {texto[:80]}"
        for caminho, texto in _textos(json.loads(relatorio.read_text(encoding="utf-8")))
        if SEGREDO.search(texto)
    ]

    assert not achados, f"{relatorio.name} carrega segredo ou caminho local: {achados}"


@pytest.mark.parametrize("relatorio", _relatorios(), ids=lambda p: p.stem)
def test_campos_certos_e_booleano_e_nao_o_que_o_modelo_escreveu(relatorio: Path) -> None:
    """A condição inteira da decisão de versionar, em uma asserção."""
    dados = json.loads(relatorio.read_text(encoding="utf-8"))

    for medido in dados.get("documentos_medidos", []):
        for campo, certo in medido.get("campos_certos", {}).items():
            assert isinstance(certo, bool), (
                f"{relatorio.name}: campos_certos[{campo}] é {type(certo).__name__}, "
                f"não booleano. O relatório está guardando o que o modelo escreveu."
            )


@pytest.mark.parametrize("relatorio", _relatorios(), ids=lambda p: p.stem)
def test_traz_a_procedencia_do_corpus(relatorio: Path) -> None:
    """Um número medido sem a procedência ao lado é um número não conferível."""
    dados = json.loads(relatorio.read_text(encoding="utf-8"))
    corpus = dados.get("corpus")
    if corpus is None:
        pytest.skip("relatório anterior ao campo `corpus`")

    for lote, gerado_com in corpus.items():
        assert gerado_com is not None, f"{lote} sem procedência"
        assert "semente" in gerado_com and "data_de_referencia" in gerado_com, (
            f"{lote}: reproduzir um lote precisa das duas, não de uma"
        )
