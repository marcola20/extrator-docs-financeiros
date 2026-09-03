"""Sinal 3: duas execuções independentes concordam campo a campo?

Cobre o que os outros dois não alcançam. O dígito verificador só protege
banco, valor e vencimento; o grounding só pega invenção, não troca de campo.
Nome do beneficiário, CNPJ e nosso número ficam sem rede nos dois — e são
justamente os campos onde uma leitura instável aparece como divergência entre
execuções.

## Duas armadilhas concretas

**O cache.** A segunda execução com o mesmo prompt e o mesmo documento é um
acerto de cache: devolveria o primeiro resultado, byte a byte, e o sinal
diria "concordam" sempre. A segunda execução tem que passar por um provedor
com o cache desligado, e é o que `provedor_para_segunda_execucao` monta.

**A temperatura.** O provedor Gemini roda com `temperature=0.0` para a
extração ser reprodutível (ADR 003). Com amostragem determinística, duas
execuções tendem a coincidir, e o que sobra deste sinal é a não-determinação
residual do serviço — real, mas fraca. Isto é uma limitação medida do sinal,
não um defeito do código, e está registrada no ADR 005: **concordância aqui
é evidência fraca; divergência é evidência forte.**
"""

from dataclasses import dataclass
from enum import StrEnum

from app.config import Settings
from app.extracao.schema_transporte import CAMPOS, BoletoExtraido
from app.llm.cache import CacheDeExtracao
from app.llm.provedor import ProvedorLLM


class ModoConsistencia(StrEnum):
    """Quando a segunda execução acontece."""

    SEMPRE = "sempre"
    """Taxa base comparável entre documentos, ao custo de dobrar a cota."""

    CONDICIONAL = "condicional"
    """Só quando outro sinal já falhou. Economiza metade, cria ponto cego."""

    NUNCA = "nunca"
    """Sem o sinal. O resultado registra que ele não rodou."""


@dataclass(frozen=True, slots=True)
class Divergencia:
    """Um campo em que as duas execuções não concordaram."""

    campo: str
    primeira: str
    segunda: str


@dataclass(frozen=True, slots=True)
class ResultadoConsistencia:
    """A comparação entre duas execuções."""

    executou: bool
    divergencias: tuple[Divergencia, ...] = ()
    motivo_de_nao_executar: str = ""
    dispensado: bool = False
    """Não rodou por decisão do operador, e não por falha.

    A diferença chega à política: sinal dispensado não bloqueia — o operador
    escolheu abrir mão dele —, sinal que falhou bloqueia, porque aí ninguém
    escolheu nada e o documento simplesmente não foi conferido.
    """

    @property
    def concordam(self) -> bool:
        return self.executou and not self.divergencias

    @property
    def taxa_de_divergencia(self) -> float:
        return len(self.divergencias) / len(CAMPOS) if self.executou else 0.0

    def descricao(self) -> str:
        if not self.executou:
            return f"não executado: {self.motivo_de_nao_executar}"
        if not self.divergencias:
            return "as duas execuções concordaram em todos os campos"
        return "; ".join(f"{d.campo}: {d.primeira!r} vs {d.segunda!r}" for d in self.divergencias)


def dispensa(motivo: str) -> ResultadoConsistencia:
    """O sinal não roda porque o operador decidiu assim."""
    return ResultadoConsistencia(executou=False, motivo_de_nao_executar=motivo, dispensado=True)


def falha(motivo: str) -> ResultadoConsistencia:
    """O sinal deveria ter rodado e não rodou. Isso bloqueia."""
    return ResultadoConsistencia(executou=False, motivo_de_nao_executar=motivo, dispensado=False)


def compara(primeira: BoletoExtraido, segunda: BoletoExtraido) -> ResultadoConsistencia:
    """Compara duas extrações campo a campo. Função pura, sem rede."""
    divergencias = tuple(
        Divergencia(campo, a, b)
        for campo in CAMPOS
        if (a := getattr(primeira, campo).strip()) != (b := getattr(segunda, campo).strip())
    )
    return ResultadoConsistencia(executou=True, divergencias=divergencias)


def deve_executar(modo: ModoConsistencia, *, algum_sinal_falhou: bool) -> tuple[bool, str]:
    """Decide se a segunda execução acontece, e diz por quê quando não."""
    match modo:
        case ModoConsistencia.SEMPRE:
            return True, ""
        case ModoConsistencia.CONDICIONAL:
            if algum_sinal_falhou:
                return True, ""
            return False, (
                "modo condicional e nenhum outro sinal falhou — é o ponto cego "
                "assumido: campos sem DV e sem grounding ficam sem conferência"
            )
        case ModoConsistencia.NUNCA:
            return False, "AUTO_CONSISTENCIA=nunca"


def provedor_para_segunda_execucao(settings: Settings) -> ProvedorLLM:
    """Um provedor igual ao normal, mas sem cache.

    Sem isto a segunda execução seria um acerto de cache e o sinal viraria
    uma tautologia: o resultado comparado consigo mesmo sempre concorda.
    """
    from app.llm import cria_provedor

    return cria_provedor(
        settings,
        cache=CacheDeExtracao(diretorio=settings.llm_cache_diretorio, ativo=False),
    )
