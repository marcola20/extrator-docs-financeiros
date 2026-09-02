"""Cache em disco de extrações, indexado pelo que determina a resposta.

Rodar o eval de novo sem ter mexido em prompt nem em documento gasta cota do
tier gratuito para receber de volta exatamente o que já se tinha. Com 500
requisições por dia (ADR 003), isso é o suficiente para travar uma tarde.

A chave é o hash de tudo que muda a resposta: provedor, modelo, instrução e
texto do documento. Mudou o prompt, mudou a chave, e a entrada velha é
ignorada sozinha — não existe cache "sujo" a ser purgado por engano. Purgar
manualmente serve para reavaliar o mesmo prompt contra o modelo de novo:

    uv run python -m app.llm.cache --limpar
"""

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.llm.provedor import ResultadoExtracao, UsoDeTokens

DIRETORIO_PADRAO = Path("dados/cache-llm")
VERSAO_FORMATO = 1


@dataclass(frozen=True)
class CacheDeExtracao:
    """Guarda e recupera resultados de extração em arquivos JSON.

    Com `ativo=False` vira um objeto inerte: toda leitura erra e toda escrita
    é descartada. É assim que a CLI desliga o cache sem o chamador precisar de
    um caminho alternativo.
    """

    diretorio: Path = DIRETORIO_PADRAO
    ativo: bool = True

    def chave(self, provedor: str, modelo: str, instrucao: str, texto: str) -> str:
        """Hash do que determina a resposta.

        As partes vão com o tamanho na frente para que fronteira de campo não
        se confunda: sem isso, ("ab", "c") e ("a", "bc") teriam a mesma chave.
        """
        digestor = hashlib.sha256()
        digestor.update(str(VERSAO_FORMATO).encode("utf-8"))
        for parte in (provedor, modelo, instrucao, texto):
            bruto = parte.encode("utf-8")
            digestor.update(f"{len(bruto)}:".encode())
            digestor.update(bruto)
        return digestor.hexdigest()

    def le[TSchema: BaseModel](
        self, chave: str, schema: type[TSchema]
    ) -> ResultadoExtracao[TSchema] | None:
        """Devolve o resultado guardado, ou `None` se não houver um utilizável.

        Entrada corrompida, de formato antigo ou que não valida mais no schema
        conta como ausência: o cache é uma economia, nunca uma fonte de erro.
        """
        if not self.ativo:
            return None

        caminho = self._caminho(chave)
        try:
            bruto = json.loads(caminho.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        if not isinstance(bruto, dict) or bruto.get("versao") != VERSAO_FORMATO:
            return None

        try:
            dados = schema.model_validate(bruto["dados"])
            uso = UsoDeTokens(entrada=bruto["uso"]["entrada"], saida=bruto["uso"]["saida"])
            return ResultadoExtracao(
                dados=dados,
                provedor=bruto["provedor"],
                modelo=bruto["modelo"],
                uso=uso,
                custo_estimado_usd=Decimal(bruto["custo_estimado_usd"]),
                do_cache=True,
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            return None

    def grava(self, chave: str, resultado: ResultadoExtracao[Any]) -> None:
        """Guarda o resultado. Resultado que já veio do cache não é regravado."""
        if not self.ativo or resultado.do_cache:
            return

        conteudo = {
            "versao": VERSAO_FORMATO,
            "provedor": resultado.provedor,
            "modelo": resultado.modelo,
            "uso": {"entrada": resultado.uso.entrada, "saida": resultado.uso.saida},
            # Decimal não é serializável em JSON e float perderia centavo:
            # o custo vai e volta como string.
            "custo_estimado_usd": str(resultado.custo_estimado_usd),
            "dados": resultado.dados.model_dump(mode="json"),
        }

        self.diretorio.mkdir(parents=True, exist_ok=True)
        caminho = self._caminho(chave)
        temporario = caminho.with_suffix(f".{os.getpid()}.tmp")
        temporario.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), "utf-8")
        temporario.replace(caminho)

    def limpa(self) -> int:
        """Apaga todas as entradas e devolve quantas foram."""
        if not self.diretorio.exists():
            return 0
        apagadas = 0
        for arquivo in self.diretorio.glob("*.json"):
            arquivo.unlink()
            apagadas += 1
        return apagadas

    def _caminho(self, chave: str) -> Path:
        return self.diretorio / f"{chave}.json"


def _analisa_argumentos(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.llm.cache",
        description="Invalida o cache de extrações do LLM.",
    )
    parser.add_argument(
        "--limpar",
        action="store_true",
        help="apaga todas as entradas do cache",
    )
    parser.add_argument(
        "--diretorio",
        type=Path,
        default=DIRETORIO_PADRAO,
        help=f"diretório do cache (padrão: {DIRETORIO_PADRAO})",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Ponto de entrada da CLI."""
    argumentos = _analisa_argumentos(argv)
    cache = CacheDeExtracao(diretorio=argumentos.diretorio)

    if not argumentos.limpar:
        entradas = len(list(argumentos.diretorio.glob("*.json")))
        print(f"{entradas} entrada(s) em {argumentos.diretorio}. Use --limpar para apagar.")
        return 0

    apagadas = cache.limpa()
    print(f"{apagadas} entrada(s) apagada(s) de {argumentos.diretorio}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
