"""Correção humana virando caso de eval, sem levar documento real para o git.

## O conflito que este módulo resolve

A ideia é direta: o que um revisor corrigiu é, por definição, um gabarito
verificado por gente — o melhor caso de teste que existe. Levá-lo para o corpus
de eval é realimentar a medição com o mundo real.

Só que o corpus de eval mora em `dados/sinteticos/`, **versionado**, num
repositório público. E a correção humana é sobre um documento **real**, que
carrega nome, CPF, CNPJ, agência, conta e valor devido — e, no boleto, a linha
digitável, que não é identificador: é a ordem de pagamento em si. A regra do
projeto sobre isso não tem exceção, e está em `dados/real/LEIA-ME.md`: documento
real nunca entra no repositório, nem por engano, porque um commit é para sempre.

Então o corpus de realimentação:

- mora em `dados/realimentacao/`, **fora do git** (o `.gitignore` já cobre
  `dados/*`), ao lado dos documentos reais que ele referencia;
- guarda o **caminho e o hash** do PDF, nunca uma cópia dele;
- é opcional em toda leitura. Num clone novo o diretório está vazio, e o eval
  diz isso em vez de falhar.

Nada aqui contradiz a decisão de versionar `resultados/`: o relatório de eval
guarda taxas, contagens e booleanos, e a trava
`tests/test_relatorios_versionados.py` impede que ele passe a guardar valor
extraído. O caso de realimentação guarda exatamente o que o relatório não pode
guardar — por isso um sobe e o outro não. Ver ADR 010.

## Por que a flag, e por que ela é desligada por padrão

Misturar casos reais com o corpus sintético sem distinção contaminaria toda
comparação com os baselines existentes: a acurácia mudaria por o corpus ter
crescido, não por o extrator ter melhorado, e não haveria como separar os dois
efeitos depois. É o mesmo erro que o ADR 006 registra sobre a passada em que
corpus e gabarito mudaram juntos.

Então: desligada por padrão, e quando ligada o relatório grava quantos casos
entraram — e a retomada recusa somar uma passada com realimentação a uma sem.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DIRETORIO_PADRAO = Path("dados/realimentacao")

ORIGEM = "correcao_humana"


@dataclass(frozen=True, slots=True)
class Procedencia:
    """De onde este caso veio. Sem isto ele seria indistinguível do sintético."""

    origem: str
    exportado_em: str
    documento_de_origem: str
    """Nome do arquivo, para quem investigar saber o que abrir. O caminho
    completo fica em `arquivo_pdf`, e nenhum dos dois entra no git."""

    hash_sha256: str
    decisao_id: int | None = None
    revisor: str = ""
    campos_corrigidos: tuple[str, ...] = ()

    def como_json(self) -> dict[str, Any]:
        return {
            "origem": self.origem,
            "exportado_em": self.exportado_em,
            "documento_de_origem": self.documento_de_origem,
            "hash_sha256": self.hash_sha256,
            "decisao_id": self.decisao_id,
            "revisor": self.revisor,
            "campos_corrigidos": list(self.campos_corrigidos),
        }

    @classmethod
    def de_json(cls, bruto: dict[str, Any]) -> "Procedencia":
        return cls(
            origem=bruto["origem"],
            exportado_em=bruto["exportado_em"],
            documento_de_origem=bruto["documento_de_origem"],
            hash_sha256=bruto["hash_sha256"],
            decisao_id=bruto.get("decisao_id"),
            revisor=bruto.get("revisor", ""),
            campos_corrigidos=tuple(bruto.get("campos_corrigidos", ())),
        )


@dataclass(frozen=True, slots=True)
class CasoDeRealimentacao:
    """Um documento real com gabarito conferido por gente."""

    arquivo_pdf: Path
    tipo: str
    campos: dict[str, Any]
    procedencia: Procedencia
    arquivo_do_par: Path | None = None
    """Só no informe, e obrigatório lá: o cruzamento entre anos precisa dos dois
    documentos, e um caso sem par entraria no eval já sem cobertura — medindo a
    ausência do par, não a leitura."""

    @property
    def utilizavel(self) -> bool:
        """O PDF ainda está onde o caso diz que está?

        Os documentos reais vivem fora do repositório e podem ter sido apagados
        — é o que se espera deles. Um caso sem arquivo não é erro: é um caso que
        não dá para medir, e o eval reporta quantos foram assim.
        """
        if not self.arquivo_pdf.is_file():
            return False
        if self.tipo == "informe":
            return self.arquivo_do_par is not None and self.arquivo_do_par.is_file()
        return True

    def como_json(self) -> dict[str, Any]:
        return {
            "arquivo_pdf": str(self.arquivo_pdf),
            "arquivo_do_par": None if self.arquivo_do_par is None else str(self.arquivo_do_par),
            "tipo": self.tipo,
            "gerado_com": None,
            "realimentacao": self.procedencia.como_json(),
            "campos": self.campos,
        }

    @classmethod
    def de_json(cls, bruto: dict[str, Any]) -> "CasoDeRealimentacao":
        do_par = bruto.get("arquivo_do_par")
        return cls(
            arquivo_pdf=Path(bruto["arquivo_pdf"]),
            arquivo_do_par=None if do_par is None else Path(do_par),
            tipo=bruto["tipo"],
            campos=bruto["campos"],
            procedencia=Procedencia.de_json(bruto["realimentacao"]),
        )


def carrega(
    diretorio: Path = DIRETORIO_PADRAO, *, tipo: str | None = None
) -> list[CasoDeRealimentacao]:
    """Lê os casos exportados. Diretório ausente devolve lista vazia, não erro.

    Num clone novo — e no CI — o diretório não existe, porque ele guarda
    referência a documento real e nunca é versionado.
    """
    if not diretorio.is_dir():
        return []

    casos = [
        CasoDeRealimentacao.de_json(json.loads(caminho.read_text(encoding="utf-8")))
        for caminho in sorted(diretorio.glob("*.json"))
    ]
    return [c for c in casos if tipo is None or c.tipo == tipo]


@dataclass(frozen=True, slots=True)
class Inventario:
    """O que há no corpus de realimentação, para o relatório poder registrar."""

    casos: int
    utilizaveis: int
    sem_arquivo: int
    revisores: tuple[str, ...]

    def como_json(self) -> dict[str, Any]:
        return {
            "casos": self.casos,
            "utilizaveis": self.utilizaveis,
            "sem_arquivo": self.sem_arquivo,
            "revisores": list(self.revisores),
        }


def inventaria(casos: Sequence[CasoDeRealimentacao]) -> Inventario:
    utilizaveis = [c for c in casos if c.utilizavel]
    return Inventario(
        casos=len(casos),
        utilizaveis=len(utilizaveis),
        sem_arquivo=len(casos) - len(utilizaveis),
        revisores=tuple(sorted({c.procedencia.revisor for c in casos if c.procedencia.revisor})),
    )


def _nome_do_arquivo(caso: CasoDeRealimentacao) -> str:
    """Nome estável por documento: reexportar atualiza em vez de duplicar."""
    return f"{caso.tipo}-{caso.procedencia.hash_sha256[:16]}.json"


def grava(caso: CasoDeRealimentacao, diretorio: Path = DIRETORIO_PADRAO) -> Path:
    """Escreve um caso. Reexportar o mesmo documento sobrescreve o caso dele."""
    diretorio.mkdir(parents=True, exist_ok=True)
    caminho = diretorio / _nome_do_arquivo(caso)
    caminho.write_text(
        json.dumps(caso.como_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return caminho


def monta(
    *,
    arquivo_pdf: Path,
    tipo: str,
    hash_sha256: str,
    payload: dict[str, Any],
    correcoes: dict[str, str],
    decisao_id: int | None = None,
    revisor: str = "",
    arquivo_do_par: Path | None = None,
) -> CasoDeRealimentacao:
    """Monta o caso aplicando as correções sobre o que o modelo tinha devolvido.

    O gabarito resultante é **o que o revisor afirmou**: os campos que ele não
    tocou ficam como o modelo os leu, porque não corrigi-los é confirmá-los —
    o revisor olhou a tela inteira antes de fechar o item.
    """
    campos = dict(payload)
    campos.update(correcoes)
    return CasoDeRealimentacao(
        arquivo_pdf=arquivo_pdf,
        arquivo_do_par=arquivo_do_par,
        tipo=tipo,
        campos=campos,
        procedencia=Procedencia(
            origem=ORIGEM,
            exportado_em=datetime.now(UTC).isoformat(timespec="seconds"),
            documento_de_origem=arquivo_pdf.name,
            hash_sha256=hash_sha256,
            decisao_id=decisao_id,
            revisor=revisor,
            campos_corrigidos=tuple(sorted(correcoes)),
        ),
    )
