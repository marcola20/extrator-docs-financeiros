"""Eval do pipeline de boleto: o único ponto que fala com a API de verdade.

Roda o corpus limpo e o adversarial, aplica o pipeline inteiro e mede o que
importa decidir. Não é teste: é medição, custa cota, e só roda quando
invocado à mão.

## A métrica principal é a taxa de escape

Acurácia média é confortável e diz pouco. O número que decide se este sistema
pode existir é outro: **dos documentos que o pipeline auto-aprovou, quantos
divergem do gabarito.** Um escape é um pagamento errado que ninguém revisou.
Acurácia de 95% com escape zero é um sistema utilizável; acurácia de 99% com
escape de 2% não é.

## Cota

Com `AUTO_CONSISTENCIA=sempre` são duas chamadas por documento. O corpus tem
43 documentos, então 86 chamadas — cabe nas 500 diárias do tier gratuito, e a
15 RPM leva uns seis minutos. Reexecutar sem mexer no prompt não gasta nada:
o cache é indexado por (provedor, modelo, instrução, documento), e mudar o
prompt muda a chave sozinho.

    uv run python eval.py                 # corpus inteiro
    uv run python eval.py --limpos        # só os 15 limpos
    uv run python eval.py --limite 5      # ensaio curto antes de gastar cota
"""

import argparse
import json
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.confianca import campos
from app.confianca.consistencia import provedor_para_segunda_execucao
from app.config import Settings, get_settings
from app.extracao.prompt import Prompt, carrega
from app.extracao.schema_transporte import CAMPOS
from app.llm import cria_provedor
from app.llm.limitador import CotaDiariaExcedida
from app.llm.provedor import ErroDeConfiguracao, ErroDeProvedor
from app.pipeline import ResultadoPipeline, processa

CORPUS_LIMPO = Path("dados/sinteticos/boletos")
CORPUS_ADVERSARIAL = Path("dados/sinteticos/boletos_adversariais")
DIRETORIO_RESULTADOS = Path("resultados")


@dataclass(slots=True)
class Caso:
    """Um documento do corpus, com o gabarito do que seria correto."""

    pdf: Path
    gabarito: dict[str, Any]
    adversarial: bool
    ataque: str | None = None

    @property
    def esperado(self) -> dict[str, str]:
        campos = self.gabarito.get("campos") or self.gabarito["extracao_correta"]
        return {k: ("" if v is None else str(v)) for k, v in campos.items()}


@dataclass(slots=True)
class Medida:
    """O que se mediu num documento."""

    caso: Caso
    resultado: ResultadoPipeline | None
    erro: str | None = None
    campos_certos: dict[str, bool] = field(default_factory=dict)

    @property
    def auto_aprovado(self) -> bool:
        return self.resultado is not None and self.resultado.auto_aprovado

    @property
    def divergiu_do_gabarito(self) -> bool:
        return any(not certo for certo in self.campos_certos.values())

    @property
    def escapou(self) -> bool:
        """Auto-aprovado e diferente do gabarito. A métrica principal."""
        return self.auto_aprovado and self.divergiu_do_gabarito


def carrega_casos(*, limpos: bool, adversariais: bool, limite: int | None) -> list[Caso]:
    casos: list[Caso] = []
    if limpos:
        for gabarito in sorted(CORPUS_LIMPO.glob("*.json")):
            dados = json.loads(gabarito.read_text(encoding="utf-8"))
            casos.append(Caso(gabarito.with_suffix(".pdf"), dados, adversarial=False))
    if adversariais:
        for gabarito in sorted(CORPUS_ADVERSARIAL.glob("*.json")):
            dados = json.loads(gabarito.read_text(encoding="utf-8"))
            casos.append(
                Caso(
                    CORPUS_ADVERSARIAL / dados["arquivo_pdf"],
                    dados,
                    adversarial=True,
                    ataque=dados["ataque"]["nome"],
                )
            )
    return casos[:limite] if limite else casos


def _compara_campos(medida: Medida) -> dict[str, bool]:
    """Compara o que o modelo extraiu com o gabarito, campo a campo.

    A definição de "mesmo valor" vem de `app.confianca.campos`, o mesmo
    módulo que a conversão para o domínio usa. Antes o eval tinha a própria
    regra, e para `banco_codigo` as duas discordavam: `748-X` era igual a
    `748` para o pipeline e diferente para o eval. O resultado foi uma taxa
    de escape de 50% acusando um erro que não existia na saída. Ver ADR 005.
    """
    if medida.resultado is None or medida.resultado.extracao is None:
        return dict.fromkeys(CAMPOS, False)

    bruto = medida.resultado.extracao.bruto
    esperado = medida.caso.esperado
    return {
        campo: campos.iguais(campo, getattr(bruto, campo), esperado.get(campo, ""))
        for campo in CAMPOS
    }


def roda(casos: Sequence[Caso], settings: Settings, prompt: Prompt) -> list[Medida]:
    """Processa o corpus, respeitando o limitador de taxa já existente."""
    provedor = cria_provedor(settings)
    segundo = provedor_para_segunda_execucao(settings)

    medidas = []
    for indice, caso in enumerate(casos, 1):
        print(f"  [{indice:3d}/{len(casos)}] {caso.pdf.name}", end="", flush=True)
        try:
            resultado = processa(
                caso.pdf, provedor, settings, prompt=prompt, provedor_da_segunda=segundo
            )
        except CotaDiariaExcedida as erro:
            print(f"  COTA ESGOTADA: {erro}")
            medidas.append(Medida(caso, None, erro=str(erro)))
            break
        except ErroDeProvedor as erro:
            print(f"  ERRO: {erro}")
            medidas.append(Medida(caso, None, erro=str(erro)))
            continue

        medida = Medida(caso, resultado)
        medida.campos_certos = _compara_campos(medida)
        medidas.append(medida)
        marca = "auto" if resultado.auto_aprovado else "revisão"
        print(f"  {marca:8} {resultado.latencia_s:5.1f}s")
    return medidas


def _percentil(valores: Sequence[float], fracao: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    indice = min(len(ordenados) - 1, round(fracao * (len(ordenados) - 1)))
    return ordenados[indice]


def resume(medidas: Sequence[Medida], prompt: Prompt, settings: Settings) -> dict[str, Any]:
    """Monta o relatório. Nenhum número aqui é estimado: todos vêm da execução."""
    com_resultado = [m for m in medidas if m.resultado is not None]
    auto = [m for m in com_resultado if m.auto_aprovado]
    escapes = [m for m in auto if m.escapou]
    adversariais = [m for m in com_resultado if m.caso.adversarial]

    por_campo = {}
    for campo in CAMPOS:
        avaliados = [m.campos_certos[campo] for m in com_resultado if m.campos_certos]
        por_campo[campo] = (sum(avaliados) / len(avaliados)) if avaliados else 0.0

    latencias = [m.resultado.latencia_s for m in com_resultado if m.resultado]
    custo = sum(
        (m.resultado.custo_estimado_usd for m in com_resultado if m.resultado), Decimal("0")
    )
    divergencias = [
        m.resultado.consistencia.taxa_de_divergencia
        for m in com_resultado
        if m.resultado and m.resultado.consistencia.executou
    ]
    adversariais_que_alteraram = [m for m in adversariais if m.divergiu_do_gabarito and m.resultado]

    return {
        "prompt": prompt.identificador,
        "modelo": com_resultado[0].resultado.extracao.modelo
        if com_resultado and com_resultado[0].resultado and com_resultado[0].resultado.extracao
        else settings.llm_modelo,
        "provedor": settings.llm_provedor,
        "auto_consistencia": settings.auto_consistencia,
        "data": datetime.now(UTC).isoformat(timespec="seconds"),
        "documentos": len(medidas),
        "processados": len(com_resultado),
        "falhas": [m.caso.pdf.name for m in medidas if m.resultado is None],
        "acuracia_por_campo": por_campo,
        "acuracia_media": statistics.fmean(por_campo.values()) if por_campo else 0.0,
        "taxa_de_auto_aprovacao": len(auto) / len(com_resultado) if com_resultado else 0.0,
        "escape_rate": len(escapes) / len(auto) if auto else 0.0,
        "escapes": [m.caso.pdf.name for m in escapes],
        "adversariais": len(adversariais),
        "adversariais_que_alteraram_a_saida": len(adversariais_que_alteraram),
        "adversariais_auto_aprovados": sum(1 for m in adversariais if m.auto_aprovado),
        "divergencia_media_entre_execucoes": statistics.fmean(divergencias)
        if divergencias
        else 0.0,
        "custo_total_usd": str(custo),
        "custo_por_documento_usd": str((custo / len(com_resultado)).quantize(Decimal("0.000001")))
        if com_resultado
        else "0",
        "latencia_p50_s": round(_percentil(latencias, 0.50), 2),
        "latencia_p95_s": round(_percentil(latencias, 0.95), 2),
    }


def imprime(relatorio: dict[str, Any]) -> None:
    print("\n" + "=" * 62)
    print(f"  prompt {relatorio['prompt']}   modelo {relatorio['modelo']}")
    print(f"  {relatorio['processados']}/{relatorio['documentos']} documentos processados")
    print("=" * 62)

    print("\n  acurácia por campo")
    for campo, taxa in relatorio["acuracia_por_campo"].items():
        barra = "█" * int(taxa * 20)
        print(f"    {campo:22} {taxa:6.1%}  {barra}")

    print("\n  decisão")
    print(f"    acurácia média            {relatorio['acuracia_media']:6.1%}")
    print(f"    taxa de auto-aprovação    {relatorio['taxa_de_auto_aprovacao']:6.1%}")
    print(f"    ESCAPE RATE               {relatorio['escape_rate']:6.1%}   <-- principal")
    if relatorio["escapes"]:
        print(f"      escaparam: {', '.join(relatorio['escapes'])}")

    print("\n  resistência a injection")
    print(f"    documentos adversariais   {relatorio['adversariais']}")
    print(f"    alteraram a saída         {relatorio['adversariais_que_alteraram_a_saida']}")
    print(f"    auto-aprovados            {relatorio['adversariais_auto_aprovados']}")

    print("\n  execução")
    print(f"    divergência entre runs    {relatorio['divergencia_media_entre_execucoes']:6.1%}")
    print(f"    custo total               US$ {relatorio['custo_total_usd']}")
    print(f"    custo por documento       US$ {relatorio['custo_por_documento_usd']}")
    print(
        f"    latência p50 / p95        {relatorio['latencia_p50_s']}s / "
        f"{relatorio['latencia_p95_s']}s"
    )
    print()


def salva(relatorio: dict[str, Any]) -> Path:
    DIRETORIO_RESULTADOS.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    caminho = DIRETORIO_RESULTADOS / f"eval-{carimbo}-{relatorio['prompt']}.json"
    caminho.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return caminho


def _analisa_argumentos(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python eval.py",
        description="Mede o pipeline de extração contra os corpora sintéticos.",
    )
    parser.add_argument("--limpos", action="store_true", help="só o corpus limpo")
    parser.add_argument("--adversariais", action="store_true", help="só o corpus adversarial")
    parser.add_argument("--limite", type=int, default=None, help="processa no máximo N")
    parser.add_argument("--prompt", type=str, default=None, help="arquivo de prompt a usar")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    argumentos = _analisa_argumentos(argv)
    so_um = argumentos.limpos or argumentos.adversariais
    casos = carrega_casos(
        limpos=argumentos.limpos or not so_um,
        adversariais=argumentos.adversariais or not so_um,
        limite=argumentos.limite,
    )
    if not casos:
        print("nenhum documento no corpus", file=sys.stderr)
        return 1

    settings = get_settings()
    prompt = carrega(argumentos.prompt) if argumentos.prompt else carrega()

    print(f"eval: {len(casos)} documento(s), prompt {prompt.identificador}")
    print(f"provedor {settings.llm_provedor}, consistência {settings.auto_consistencia}\n")

    inicio = time.monotonic()
    try:
        medidas = roda(casos, settings, prompt)
    except ErroDeConfiguracao as erro:
        print(f"\nconfiguração incompleta: {erro}", file=sys.stderr)
        return 1
    relatorio = resume(medidas, prompt, settings)
    relatorio["duracao_total_s"] = round(time.monotonic() - inicio, 1)

    imprime(relatorio)
    caminho = salva(relatorio)
    print(f"  relatório em {caminho}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
