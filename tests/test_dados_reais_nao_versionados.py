"""Trava contra commit acidental de documento real.

`dados/real/` guarda documentos de verdade durante o teste local, e eles
carregam dado pessoal de terceiros. O `.gitignore` já os mantém de fora,
mas `git add --force` passa por cima dele — este teste é a segunda trava,
que pega o arquivo depois de rastreado, antes que o commit vire histórico.
"""

import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DADOS_REAIS = "dados/real"

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

    assert ignorado.returncode == 0, (
        f"{documento.relative_to(RAIZ)} não é ignorado pelo .gitignore; "
        "a regra de dados/real/ foi afrouxada."
    )
