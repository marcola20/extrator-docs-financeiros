"""Travas contra commit acidental de dado real.

São duas entradas diferentes, e por isso dois mecanismos:

1. **Documento inteiro em `dados/real/`.** O `.gitignore` mantém a pasta de
   fora, mas `git add --force` passa por cima dele. A trava confere o índice
   do git antes que o commit vire histórico.
2. **Linha digitável solta em `tests/`.** Foi o caso que escapou: uma linha
   digitável de origem real colada num arquivo de teste não passa por
   `dados/real/`, então a trava do índice não a vê. Ela é o dado mais
   sensível de um boleto — o instrumento de pagamento em si — e a trava aqui
   exige que toda linha válida em `tests/` tenha procedência declarada.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

from app.dominio.digito_verificador import TAMANHO_LINHA_DIGITAVEL, valida_linha_digitavel

RAIZ = Path(__file__).resolve().parents[1]
DADOS_REAIS = "dados/real"

# Fora de um clone — um sdist, um `git archive` — não há índice, e o git
# responde 128 a tudo. Pular é honesto; deixar o 128 virar "a regra foi
# afrouxada" seria um alarme falso, que é o pior defeito de uma trava.
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

# Únicos arquivos de dados/real/ que podem estar no git: a explicação da
# pasta e os .gitkeep que preservam a estrutura em um clone novo.
ARQUIVO_PERMITIDO = f"{DADOS_REAIS}/LEIA-ME.md"
NOME_PERMITIDO = ".gitkeep"


def _git(*argumentos: str) -> str:
    resultado = subprocess.run(
        ["git", *argumentos],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=True,
    )
    return resultado.stdout


@exige_repositorio
def test_nenhum_documento_real_esta_rastreado() -> None:
    rastreados = _git("ls-files", "--", DADOS_REAIS).splitlines()

    proibidos = [
        caminho
        for caminho in rastreados
        if caminho != ARQUIVO_PERMITIDO and Path(caminho).name != NOME_PERMITIDO
    ]

    assert not proibidos, (
        "Documento real rastreado pelo git — dado pessoal de terceiros não "
        "pode entrar no repositório. Remova do índice antes de commitar:\n"
        + "\n".join(f"  git rm --cached {caminho}" for caminho in proibidos)
    )


@exige_repositorio
def test_gitignore_bloqueia_documento_novo_em_dados_reais() -> None:
    """A primeira trava: um arquivo solto na pasta já nasce ignorado."""
    documento = RAIZ / DADOS_REAIS / "boletos" / "__documento-de-teste.pdf"
    documento.touch()
    try:
        ignorado = subprocess.run(
            ["git", "check-ignore", "--quiet", str(documento)],
            cwd=RAIZ,
            check=False,
        )
    finally:
        documento.unlink()

    # 0 = ignorado, 1 = versionável, qualquer outro = o git falhou.
    assert ignorado.returncode in (0, 1), f"git check-ignore falhou: {ignorado.returncode}"
    assert ignorado.returncode == 0, (
        f"{documento.relative_to(RAIZ)} não é ignorado pelo .gitignore; "
        "a regra de dados/real/ foi afrouxada."
    )


# --------------------------------------------------------------------------
# Trava 2: linha digitável não declarada em tests/
# --------------------------------------------------------------------------

DIRETORIO_TESTES = RAIZ / "tests"
CORPUS_SINTETICO = RAIZ / "dados/sinteticos/boletos"

# Toda linha digitável que pode aparecer em tests/, com a procedência
# declarada. A lista é explícita de propósito: acrescentar uma linha aqui é
# um ato consciente, com o autor afirmando de onde ela veio. Uma linha de
# boleto real declarada como "vetor público" seria mentira, não descuido.
LINHAS_APROVADAS: dict[str, str] = {
    "34191090080000001234456789000009715700000123456": (
        "montada à mão para os testes de DV — banco 341, R$ 1.234,56"
    ),
    "42297115040000195441160020034520268610000054659": (
        "vetor público: github.com/Tagliatti/Boleto-Validator-PHP"
    ),
    "23793380296099605290241006333300689690000143014": (
        "vetor público: github.com/amendoncabh/validador-de-boletos"
    ),
}

# Corridas de dígitos numa mesma linha de texto, tolerando a formatação
# visual da linha digitável (pontos, espaços, hífens). Não atravessa quebra
# de linha: uma linha digitável é escrita de uma vez.
_CORRIDA_DE_DIGITOS = re.compile(r"\d[\d.\s-]*\d")
_NAO_DIGITO = re.compile(r"\D")

_IGNORADOS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def _linhas_do_gerador() -> set[str]:
    """Linhas digitáveis do corpus sintético versionado.

    São produto do gerador deste projeto, então podem aparecer num teste sem
    declaração — não há documento de ninguém por trás delas.
    """
    if not CORPUS_SINTETICO.is_dir():
        return set()
    linhas: set[str] = set()
    for gabarito in CORPUS_SINTETICO.glob("*.json"):
        campos = json.loads(gabarito.read_text(encoding="utf-8")).get("campos", {})
        linha = campos.get("linha_digitavel")
        if isinstance(linha, str):
            linhas.add(_NAO_DIGITO.sub("", linha))
    return linhas


def _arquivos_de_teste() -> list[Path]:
    return [
        caminho
        for caminho in sorted(DIRETORIO_TESTES.rglob("*"))
        if caminho.is_file() and not _IGNORADOS & set(caminho.parts)
    ]


def _linhas_validas_em(arquivo: Path) -> list[tuple[int, str]]:
    """Toda sequência de 47 dígitos com os quatro DVs fechando."""
    try:
        texto = arquivo.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        # Binário ou ilegível não carrega linha digitável colada por engano.
        return []

    achados: list[tuple[int, str]] = []
    for numero, conteudo in enumerate(texto.splitlines(), 1):
        for corrida in _CORRIDA_DE_DIGITOS.finditer(conteudo):
            digitos = _NAO_DIGITO.sub("", corrida.group())
            for inicio in range(len(digitos) - TAMANHO_LINHA_DIGITAVEL + 1):
                janela = digitos[inicio : inicio + TAMANHO_LINHA_DIGITAVEL]
                if valida_linha_digitavel(janela).valido:
                    achados.append((numero, janela))
    return achados


def _mascara(linha: str) -> str:
    """Identifica a linha sem reproduzi-la.

    A mensagem de falha vai para o terminal e para o log de CI. Uma trava
    contra vazamento que imprime o dado vazado não serve para nada.
    """
    return f"banco {linha[:3]}, final {linha[-4:]}"


def test_nenhuma_linha_digitavel_sem_procedencia_em_tests() -> None:
    """Linha digitável válida em tests/ tem que ter origem declarada.

    A linha digitável é o instrumento de pagamento do boleto: quem tem os 47
    dígitos paga o documento, e o campo livre identifica o beneficiário.
    Tirar nome e CPF ao redor não a torna anônima. Ver dados/real/LEIA-ME.md.
    """
    permitidas = set(LINHAS_APROVADAS) | _linhas_do_gerador()

    nao_declaradas = [
        f"  {arquivo.relative_to(RAIZ)}:{numero} ({_mascara(linha)})"
        for arquivo in _arquivos_de_teste()
        for numero, linha in _linhas_validas_em(arquivo)
        if linha not in permitidas
    ]

    assert not nao_declaradas, (
        "Linha digitável válida sem procedência declarada em tests/:\n"
        + "\n".join(nao_declaradas)
        + "\n\nSe veio de um boleto real, remova: a linha digitável é o "
        "instrumento de pagamento, e commit é permanente.\n"
        "Se é vetor público ou fixture montada à mão, declare em "
        "LINHAS_APROVADAS, com a origem."
    )
