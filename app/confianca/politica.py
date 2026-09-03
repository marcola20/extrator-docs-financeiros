"""Roteamento final: combina os quatro sinais numa decisão.

Função pura. Recebe os sinais já calculados e devolve a rota com a razão
escrita, campo a campo. Não chama modelo, não abre arquivo, não decide
sozinha o que cada sinal significa — só como eles se somam.

## Como os quatro se somam

Não há peso, não há pontuação, não há limiar. **Qualquer sinal que reprove
manda o documento para revisão.** É a mesma escolha do ADR 002 e da política
de sanitização: falso positivo custa tempo de revisor, falso negativo custa um
pagamento errado, e os dois não se equivalem.

A ordem em que aparecem no relatório é a ordem de força da evidência:

1. **Sanitização** — achado nunca auto-aprova (política da Fase 1.2).
2. **Dígito verificador** — a única garantia aritmética (ADR 002).
3. **Grounding** — pega invenção, não pega troca de campo.
4. **Auto-consistência** — divergência é evidência forte; concordância, fraca.

Um sinal que **não rodou** não conta como aprovado. É a mesma regra da Fase
1.2: não achar é diferente de não procurar, e a decisão registra a diferença.
A exceção é o sinal **dispensado** — desligado por configuração. Aí houve uma
escolha, ela fica registrada no relatório, e o ponto cego é do operador.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from app.confianca.consistencia import ResultadoConsistencia
from app.confianca.grounding import ResultadoGrounding
from app.extracao.extrator import Extracao
from app.seguranca.politica import Decisao as DecisaoDeSanitizacao


class Rota(StrEnum):
    AUTO_APROVADO = "auto_aprovado"
    REVISAO_HUMANA = "revisao_humana"


class Sinal(StrEnum):
    SANITIZACAO = "sanitizacao"
    DIGITO_VERIFICADOR = "digito_verificador"
    GROUNDING = "grounding"
    CONSISTENCIA = "consistencia"


@dataclass(frozen=True, slots=True)
class Veredito:
    """O que um sinal disse."""

    sinal: Sinal
    aprovou: bool
    executou: bool
    detalhe: str
    dispensado: bool = False
    """O operador desligou este sinal de propósito."""

    @property
    def bloqueia(self) -> bool:
        """Reprovar bloqueia. Não ter rodado também — a menos que dispensado.

        A distinção importa: um sinal desligado por configuração é uma
        escolha registrada, e bloquear tudo tornaria o modo inútil. Um sinal
        que deveria ter rodado e não rodou é um documento não conferido, e
        esse bloqueia, pela mesma razão da Fase 1.2.
        """
        if self.dispensado:
            return False
        return not (self.executou and self.aprovou)


@dataclass(frozen=True, slots=True)
class DecisaoFinal:
    """A rota e a razão, com o veredito de cada sinal."""

    rota: Rota
    vereditos: tuple[Veredito, ...]
    campos_a_revisar: tuple[str, ...] = field(default_factory=tuple)

    @property
    def auto_aprovado(self) -> bool:
        return self.rota is Rota.AUTO_APROVADO

    @property
    def bloqueadores(self) -> tuple[Veredito, ...]:
        return tuple(v for v in self.vereditos if v.bloqueia)

    def para_revisor(self) -> str:
        linhas = [f"rota: {self.rota.value}"]
        for veredito in self.vereditos:
            marca = "ok " if not veredito.bloqueia else "BLOQUEIA"
            linhas.append(f"  [{marca}] {veredito.sinal.value}: {veredito.detalhe}")
        if self.campos_a_revisar:
            linhas.append(f"  campos a conferir: {', '.join(self.campos_a_revisar)}")
        return "\n".join(linhas)


def decide(
    *,
    sanitizacao: DecisaoDeSanitizacao,
    extracao: Extracao,
    grounding: ResultadoGrounding,
    consistencia: ResultadoConsistencia,
) -> DecisaoFinal:
    """Combina os quatro sinais. Pura: nada aqui toca rede ou disco."""
    vereditos = (
        Veredito(
            sinal=Sinal.SANITIZACAO,
            aprovou=sanitizacao.auto_aprovavel,
            executou=True,
            detalhe=sanitizacao.motivo,
        ),
        Veredito(
            sinal=Sinal.DIGITO_VERIFICADOR,
            aprovou=extracao.fecha_no_dominio,
            executou=True,
            detalhe=(
                "banco, valor e vencimento conferem com a linha digitável"
                if extracao.fecha_no_dominio
                else f"não fecha: {extracao.erro_de_dominio}"
            ),
        ),
        Veredito(
            sinal=Sinal.GROUNDING,
            aprovou=grounding.aprovado,
            executou=True,
            detalhe=grounding.descricao(),
        ),
        Veredito(
            sinal=Sinal.CONSISTENCIA,
            aprovou=consistencia.concordam,
            executou=consistencia.executou,
            detalhe=consistencia.descricao(),
            dispensado=consistencia.dispensado,
        ),
    )

    campos = tuple(
        sorted({c.campo for c in grounding.ausentes} | {d.campo for d in consistencia.divergencias})
    )
    bloqueado = any(v.bloqueia for v in vereditos)

    return DecisaoFinal(
        rota=Rota.REVISAO_HUMANA if bloqueado else Rota.AUTO_APROVADO,
        vereditos=vereditos,
        campos_a_revisar=campos,
    )
