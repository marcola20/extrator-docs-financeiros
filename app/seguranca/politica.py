"""Política de roteamento: o que fazer com um documento depois da sanitização.

Separada dos detectores de propósito. Detectar e decidir mudam por motivos
diferentes — um padrão novo é conhecimento sobre ataques, uma regra nova de
roteamento é decisão de risco — e separadas dá para testar a decisão sem
gerar um PDF.

## As três saídas, e as duas que foram recusadas

**Rejeitar o documento** foi recusado. Falso positivo é certo de acontecer, e
rejeitar transforma cada um deles em um boleto legítimo barrado. O custo do
erro cai sobre quem não fez nada.

**Sanitizar em silêncio** — apagar o trecho suspeito e seguir — foi recusado
por ser pior: esconde o ataque exatamente de quem deveria vê-lo. Um documento
adversarial que passa limpo pelo pipeline não deixa nem rastro de que houve
tentativa, e a segunda tentativa do atacante começa do zero.

O que sobra: **qualquer achado tira a auto-aprovação**, e o documento vai
para revisão humana com os trechos e onde estão. É a decisão que erra para o
lado barato — falso positivo custa tempo de revisor, falso negativo custa um
pagamento errado.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.seguranca.ingestao import DETECTOR_DIVERGENCIA_OCR
from app.seguranca.sanitizador import Achado, ResultadoSanitizacao, Severidade


class Rota(StrEnum):
    """Para onde o documento vai."""

    AUTOMATICO = "automatico"
    """Elegível a seguir sem revisão — se a validação determinística passar."""

    REVISAO_HUMANA = "revisao_humana"
    """Precisa de um par de olhos antes de qualquer aprovação."""


@dataclass(frozen=True, slots=True)
class Decisao:
    """A rota e por quê, com o que o revisor precisa olhar."""

    rota: Rota
    motivo: str
    achados: tuple[Achado, ...] = ()

    @property
    def auto_aprovavel(self) -> bool:
        return self.rota is Rota.AUTOMATICO

    def para_revisor(self) -> str:
        """Texto com os trechos suspeitos e a localização de cada um."""
        if not self.achados:
            return self.motivo
        linhas = [self.motivo, ""]
        for achado in self.achados:
            linhas.append(f"- {achado.local}: {achado.detalhe}")
            linhas.append(f"    {achado.trecho!r}")
        return "\n".join(linhas)


def decide(resultado: ResultadoSanitizacao) -> Decisao:
    """Decide a rota do documento a partir do que a sanitização viu.

    Nunca rejeita e nunca altera o documento: a única alavanca é exigir
    revisão humana.
    """
    if resultado.achados:
        severidade = resultado.severidade_maxima
        quantidade = len(resultado.achados)
        return Decisao(
            rota=Rota.REVISAO_HUMANA,
            motivo=(
                f"{quantidade} achado(s) de sanitização, severidade máxima "
                f"{severidade}. O documento não é auto-aprovável; confira os "
                f"trechos abaixo contra o que está impresso na página."
            ),
            achados=resultado.achados,
        )

    if not resultado.houve_o_que_inspecionar:
        return Decisao(
            rota=Rota.REVISAO_HUMANA,
            motivo=(
                "o documento não tem camada de texto, então os detectores "
                "rodaram sobre nada. Isso não é um documento limpo: é um "
                "documento não inspecionado."
            ),
        )

    if DETECTOR_DIVERGENCIA_OCR not in resultado.detectores_executados:
        return Decisao(
            rota=Rota.REVISAO_HUMANA,
            motivo=(
                "a comparação texto/imagem não rodou neste documento, então "
                "texto invisível por opacidade ou modo de renderização não foi "
                "procurado. Ausência de achado aqui não é atestado."
            ),
        )

    return Decisao(
        rota=Rota.AUTOMATICO,
        motivo=(
            "nenhum achado de sanitização. A aprovação ainda depende da "
            "validação determinística do ADR 002 — é ela, e não este módulo, "
            "que garante valor e vencimento."
        ),
    )


def severidade_bloqueia(severidade: Severidade | None) -> bool:
    """Toda severidade tira a auto-aprovação. Existe para o teste dizer isso."""
    return severidade is not None
