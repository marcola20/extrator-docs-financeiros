"""Carregamento do prompt versionado.

O prompt fica em arquivo, com número de versão no cabeçalho, e não embutido
no código. O eval precisa dizer qual versão produziu qual resultado: comparar
duas execuções sem saber se o prompt mudou entre elas não mede nada.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

DIRETORIO_PROMPTS = Path(__file__).parent / "prompts"
PROMPT_BOLETO = "boleto-v2.md"
"""A versão em uso. As anteriores ficam no diretório: um relatório de eval
carimbado com `boleto-v1` tem que continuar reproduzível."""

PROMPT_INFORME = "informe-v1.md"
"""Um prompt para os dois layouts do informe, não um por layout. Ver ADR 009."""

_CABECALHO = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Prompt:
    """Um prompt versionado, com o identificador que vai para o resultado."""

    nome: str
    versao: int
    texto: str
    digest: str
    """Hash do texto. Pega edição que esqueceu de subir a versão."""

    @property
    def identificador(self) -> str:
        return f"{self.nome}-v{self.versao}+{self.digest[:8]}"


def carrega(arquivo: str = PROMPT_BOLETO) -> Prompt:
    """Lê um prompt do diretório versionado."""
    caminho = DIRETORIO_PROMPTS / arquivo
    bruto = caminho.read_text(encoding="utf-8")

    cabecalho = _CABECALHO.match(bruto)
    if cabecalho is None:
        raise ValueError(f"{caminho} não tem cabeçalho com nome e versão")

    campos = dict(linha.split(":", 1) for linha in cabecalho.group(1).splitlines() if ":" in linha)
    texto = bruto[cabecalho.end() :].strip()
    if not texto:
        raise ValueError(f"{caminho} não tem corpo")

    return Prompt(
        nome=campos["nome"].strip(),
        versao=int(campos["versao"].strip()),
        texto=texto,
        digest=hashlib.sha256(texto.encode("utf-8")).hexdigest(),
    )
