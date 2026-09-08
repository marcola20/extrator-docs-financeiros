"""O que os evals dos dois documentos compartilham.

Nasceu de uma extração, não de um projeto: o eval de informe precisava de
retomada, procedência de corpus, histórico de passadas e os blocos de
impressão que dizem "isto é um relatório somado" e "isto aqui ficou fora da
medição". Reescrevê-los teria criado uma segunda versão das mesmas regras —
o erro que o ADR 005 registra sobre a definição de igualdade de campo.

Nada aqui sabe o que é boleto ou informe. O que é específico de cada corpus
— quais campos existem, o que conta como ataque vencido, quais métricas o
relatório traz — fica em `eval.py` e em `app.avaliacao.informe`.
"""

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

DIRETORIO_RESULTADOS = Path("resultados")


class RetomadaInvalida(Exception):
    """O relatório apontado não pode ser somado com esta execução."""


class RegistroLido(Protocol):
    """O mínimo que a retomada precisa saber de um documento medido."""

    documento: str
    passada: int

    @property
    def pendente(self) -> bool: ...


def percentil(valores: Sequence[float], fracao: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    indice = min(len(ordenados) - 1, round(fracao * (len(ordenados) - 1)))
    return ordenados[indice]


def resumo_do_erro(mensagem: str | None, limite: int = 96) -> str:
    """Uma linha. A mensagem inteira fica no JSON, que é onde se investiga."""
    if not mensagem:
        return "sem mensagem"
    achatada = " ".join(mensagem.split())
    return achatada if len(achatada) <= limite else achatada[: limite - 1] + "…"


def procedencia_do_corpus(itens: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    """Semente e data de referência de cada corpus carregado.

    Reproduzir um lote precisa das duas, e a mesma semente em outro dia gera
    outro corpus em silêncio — ver a seção de corpus reproduzível no CLAUDE.md.
    O relatório grava isso para que somar duas passadas possa ser recusado
    quando o corpus mudou entre elas.
    """
    procedencia: dict[str, Any] = {}
    for chave, gerado_com in itens:
        procedencia.setdefault(chave, gerado_com)
    return procedencia


def registros_do_relatorio[R](
    relatorio: dict[str, Any], caminho: Path, de_json: Callable[[dict[str, Any]], R]
) -> list[R]:
    brutos = relatorio.get("documentos_medidos")
    if brutos is None:
        raise RetomadaInvalida(
            f"{caminho.name} não tem 'documentos_medidos': é anterior à retomada e "
            f"guarda só as taxas, não o que cada documento mediu. Não dá para somar "
            f"o que ele não registrou — rode a passada inteira; a partir dela, "
            f"retomar funciona."
        )
    return [de_json(bruto) for bruto in brutos]


def confere_compatibilidade(
    relatorio: dict[str, Any],
    caminho: Path,
    *,
    esperado: Sequence[tuple[str, Any]],
) -> None:
    """Recusa somar duas passadas que não mediram a mesma coisa.

    Retomar é útil justamente quando o provedor está instável, e é exatamente
    aí que o risco aparece: entre a primeira passada e a retomada dá tempo de
    trocar o prompt, o provedor, o modo de consistência ou o corpus, e o
    relatório somado esconderia a troca dentro de uma média.
    """
    divergencias = [
        f"{campo}: {relatorio.get(campo)!r} antes, {agora!r} agora"
        for campo, agora in esperado
        if relatorio.get(campo) != agora
    ]
    if divergencias:
        raise RetomadaInvalida(
            f"{caminho.name} mediu outra coisa; somar as duas passadas daria um "
            f"número que não corresponde a execução nenhuma:\n    " + "\n    ".join(divergencias)
        )


def monta_passada_nova(
    numero: int, quantos: int, retomada_de: Path | None = None
) -> dict[str, Any]:
    passada: dict[str, Any] = {
        "numero": numero,
        "data": datetime.now(UTC).isoformat(timespec="seconds"),
        # Quantos documentos esta passada mandou ao modelo, que não é quantos
        # ela mediu: os que falharam foram tentados e não medidos.
        "documentos_tentados": quantos,
    }
    if retomada_de is not None:
        passada["retomada_de"] = retomada_de.name
    return passada


def _normaliza_passada(passada: dict[str, Any]) -> dict[str, Any]:
    """Aceita o nome antigo do campo, dos relatórios gravados antes de ele mudar.

    Transitório: some quando não houver mais relatório de 2026-09-04 para
    retomar. Fica aqui, e não na impressão, para o relatório somado sair já com
    o nome certo em vez de propagar o antigo.
    """
    if "documentos_tentados" in passada or "documentos_medidos" not in passada:
        return passada
    normalizada = dict(passada)
    normalizada["documentos_tentados"] = normalizada.pop("documentos_medidos")
    return normalizada


def passadas_anteriores(relatorio: dict[str, Any]) -> list[dict[str, Any]]:
    """As passadas que o relatório anterior carregava, ou ele próprio como a primeira."""
    registradas = relatorio.get("passadas")
    if registradas:
        return [_normaliza_passada(passada) for passada in registradas]
    return [
        {
            "numero": 1,
            "data": relatorio.get("data"),
            "documentos_tentados": relatorio.get("documentos", 0),
        }
    ]


def imprime_cabecalho(relatorio: dict[str, Any]) -> None:
    print("\n" + "=" * 62)
    print(f"  prompt {relatorio['prompt']}   modelo {relatorio['modelo']}")
    print(f"  {relatorio['processados']}/{relatorio['documentos']} documentos processados")
    print("=" * 62)


def imprime_origem(relatorio: dict[str, Any]) -> None:
    """Um relatório somado mede o corpus inteiro, mas não num instante só.

    A taxa é legítima; a leitura "isto é uma passada" não é, e quem lê tem que
    ver de quantas partes o número foi feito antes de compará-lo com outro.
    """
    passadas = relatorio.get("passadas") or []
    if len(passadas) <= 1:
        return
    print("\n  origem")
    for passada in passadas:
        origem = passada.get("retomada_de")
        print(
            f"    passada {passada.get('numero')}  {passada.get('data')}  "
            f"{passada.get('documentos_tentados')} tentados"
            f"{f'  (retomada de {origem})' if origem else ''}"
        )
    print(
        f"    RELATÓRIO SOMADO de {len(passadas)} passadas em momentos "
        f"diferentes; mesmo prompt, modelo e corpus."
    )


def imprime_fora_da_medicao(relatorio: dict[str, Any]) -> None:
    """Antes de qualquer taxa, o que ficou de fora dela.

    Uma passada que perdeu documentos pode reportar acurácia melhor que uma
    completa — perder os difíceis sobe a média — e quem lê precisa ver isso
    antes dos números, não depois de tirar uma conclusão deles.
    """
    if not (relatorio["falhas"] or relatorio["nao_tentados"]):
        return
    print("\n  fora da medição")
    for falha in relatorio["falhas"]:
        print(
            f"    {falha['documento']:24} {falha['tipo'] or 'erro'}: "
            f"{resumo_do_erro(falha['erro'])}"
        )
    if relatorio["nao_tentados"]:
        print(
            f"    {len(relatorio['nao_tentados'])} não tentados "
            f"(a cota acabou): {', '.join(relatorio['nao_tentados'][:4])}"
            f"{', …' if len(relatorio['nao_tentados']) > 4 else ''}"
        )
    print("    CORPUS PARCIAL: não compare estas taxas com as de uma passada completa.")


def salva(relatorio: dict[str, Any]) -> Path:
    DIRETORIO_RESULTADOS.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    caminho = DIRETORIO_RESULTADOS / f"eval-{carimbo}-{relatorio['prompt']}.json"
    caminho.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return caminho
