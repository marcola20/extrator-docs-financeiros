"""Alinhamento de linha e as três métricas que documento multi-registro exige.

## Por que acurácia por campo não basta

No boleto, "o modelo acertou `valor`?" é uma pergunta com resposta. No informe,
`valor` é uma coluna com N linhas, e um número só desmonta três falhas
diferentes na mesma média:

- **o modelo perdeu linhas** — um quadro que quebrou entre páginas e teve a
  segunda metade ignorada;
- **o modelo inventou linhas** — repetiu um bloco, ou leu o cabeçalho como
  lançamento;
- **o modelo leu mal um número** — achou todas as linhas e errou um valor.

As três produzem "acurácia de valor abaixo de 100%" e pedem correções opostas.
Por isso aqui saem três números separados: recall de linha, precisão de linha,
e acurácia de campo **restrita às linhas que casaram**. Só o terceiro fala
sobre leitura de número; os dois primeiros falam sobre estrutura.

## A chave de casamento

O casamento é por `identificador`, comparado após normalização de espaço e
caixa. De onde vem o identificador depende do layout (ADR 007):

| Layout | Chave |
|---|---|
| `fonte_pagadora` | o número da linha no formulário: `3.1`, `4.7` |
| `instituicao_financeira` | a especificação impressa: `CDB 1234567` |

A normalização vai até onde a diferença é de formatação da mesma chave —
espaço duplicado, caixa. Não vai além: um dígito trocado em `CDB 1234567` é
outra conta, e tem de continuar sendo linha não casada.

O casamento é **por ocorrência**: se a página imprime a mesma chave duas vezes,
são duas linhas a devolver. Ver a nota de `Alinhamento.repetidas`.

**Consequência que precisa ficar explícita:** no layout bancário a chave é
texto livre lido da página, então errá-la não aparece como erro de campo,
aparece como queda de recall *e* de precisão — a linha certa fica faltando e
a linha com chave errada fica sobrando. É o comportamento correto, e é o elo
mais frágil da medição.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

ESPACOS = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class LinhaMedida:
    """Uma linha vista pela medição: a chave e os campos comparáveis."""

    identificador: str
    campos: Mapping[str, str]

    @property
    def chave(self) -> str:
        """A forma normalizada usada no casamento. Ver a nota do módulo."""
        return ESPACOS.sub(" ", self.identificador).strip().casefold()


@dataclass(frozen=True, slots=True)
class Alinhamento:
    """O resultado de casar as linhas devolvidas com as do gabarito."""

    casadas: tuple[tuple[LinhaMedida, LinhaMedida], ...] = ()
    """Pares (esperada, obtida) com a mesma chave."""
    faltantes: tuple[LinhaMedida, ...] = ()
    """Estão no documento e o modelo não devolveu."""
    inventadas: tuple[LinhaMedida, ...] = ()
    """O modelo devolveu e não existem no documento."""
    repetidas: tuple[str, ...] = ()
    """Chaves que o modelo devolveu mais vezes do que a página as imprime.

    Cada ocorrência a mais conta como inventada: devolver duas vezes uma conta
    que aparece uma é afirmar um lançamento que não houve. Sem isto, o quadro
    duplicado do corpus adversarial sairia com recall e precisão perfeitos.

    O casamento é por **ocorrência**, e não por chave distinta, e a diferença
    só aparece no gabarito adversarial. A página do `quadro_duplicado` imprime
    a mesma conta duas vezes; ler as duas é ler a página como ela está (ADR 006)
    e é o que faz a soma não fechar. Um modelo que **deduplica em silêncio**
    devolve uma linha onde a página tem duas, e isso tem de sair como linha
    faltando — se a chave distinta bastasse para casar, o recall daria 100%
    sobre um documento em que metade das linhas impressas não foi devolvida, e
    a métrica ficaria cega justamente no ataque que ela existe para enxergar.
    """

    @property
    def esperadas(self) -> int:
        return len(self.casadas) + len(self.faltantes)

    @property
    def obtidas(self) -> int:
        return len(self.casadas) + len(self.inventadas)

    @property
    def recall(self) -> float:
        """Quantas linhas do documento foram encontradas.

        Sem linha esperada não há recall a reportar: devolve 1.0, porque não
        faltou nada. É o quadro vazio, que o corpus tem de propósito.
        """
        return len(self.casadas) / self.esperadas if self.esperadas else 1.0

    @property
    def precisao(self) -> float:
        """Quantas linhas devolvidas existem mesmo no documento."""
        return len(self.casadas) / self.obtidas if self.obtidas else 1.0

    def descricao(self) -> str:
        partes = [f"{len(self.casadas)} casadas"]
        if self.faltantes:
            partes.append(f"{len(self.faltantes)} faltando ({_chaves(self.faltantes)})")
        if self.inventadas:
            partes.append(f"{len(self.inventadas)} sobrando ({_chaves(self.inventadas)})")
        if self.repetidas:
            partes.append(f"{len(self.repetidas)} repetidas ({', '.join(self.repetidas)})")
        return "; ".join(partes)


def _chaves(linhas: Sequence[LinhaMedida], limite: int = 4) -> str:
    nomes = [linha.identificador for linha in linhas[:limite]]
    return ", ".join(nomes) + (", …" if len(linhas) > limite else "")


def alinha(esperadas: Sequence[LinhaMedida], obtidas: Sequence[LinhaMedida]) -> Alinhamento:
    """Casa as linhas por chave normalizada.

    A ordem não importa: um modelo que devolve as linhas trocadas de lugar leu
    o documento certo, e penalizá-lo por isso mediria formatação, não leitura.
    """
    pendentes: dict[str, list[LinhaMedida]] = {}
    for linha in esperadas:
        pendentes.setdefault(linha.chave, []).append(linha)

    casadas: list[tuple[LinhaMedida, LinhaMedida]] = []
    inventadas: list[LinhaMedida] = []
    repetidas: list[str] = []

    for obtida in obtidas:
        fila = pendentes.get(obtida.chave)
        if not fila:
            # Não sobrou linha esperada com essa chave. Ou ela não existe no
            # documento, ou o modelo devolveu mais ocorrências do que a página
            # tem — e a segunda forma é o `quadro_duplicado` visto do outro
            # lado, então ela sai marcada.
            if any(esperada.chave == obtida.chave for esperada in esperadas):
                repetidas.append(obtida.identificador)
            inventadas.append(obtida)
            continue
        casadas.append((fila.pop(0), obtida))

    faltantes = [linha for fila in pendentes.values() for linha in fila]

    return Alinhamento(
        casadas=tuple(casadas),
        faltantes=tuple(faltantes),
        inventadas=tuple(inventadas),
        repetidas=tuple(repetidas),
    )


@dataclass(frozen=True, slots=True)
class AcuraciaDeCampo:
    """Acurácia de um campo, com o denominador ao lado.

    O denominador vai junto porque 100% sobre duas linhas casadas não afirma o
    mesmo que 100% sobre quarenta, e um alinhamento ruim encolhe o denominador
    justamente onde a leitura foi pior. Ler a acurácia sem ele inverte a
    conclusão.
    """

    campo: str
    certos: int
    avaliados: int

    @property
    def taxa(self) -> float:
        return self.certos / self.avaliados if self.avaliados else 0.0


@dataclass(frozen=True, slots=True)
class MetricasDeLinha:
    """As três medidas de um documento multi-registro, lado a lado."""

    alinhamento: Alinhamento
    por_campo: tuple[AcuraciaDeCampo, ...] = field(default=())

    @property
    def recall(self) -> float:
        return self.alinhamento.recall

    @property
    def precisao(self) -> float:
        return self.alinhamento.precisao

    def acuracia(self, campo: str) -> float:
        for medida in self.por_campo:
            if medida.campo == campo:
                return medida.taxa
        raise KeyError(f"campo {campo!r} não foi medido")

    def descricao(self) -> str:
        campos = ", ".join(f"{m.campo} {m.taxa:.1%} ({m.avaliados})" for m in self.por_campo)
        return (
            f"recall {self.recall:.1%}, precisão {self.precisao:.1%} "
            f"[{self.alinhamento.descricao()}] — {campos}"
        )


def mede(
    esperadas: Sequence[LinhaMedida],
    obtidas: Sequence[LinhaMedida],
    campos: Sequence[str],
    iguais: Callable[[str, str, str], bool],
) -> MetricasDeLinha:
    """Alinha as linhas e mede a acurácia de campo **só nas que casaram**.

    `iguais` é a definição de igualdade por campo — na prática
    `app.confianca.campos.iguais`, que é a única do projeto (ADR 005). Ela
    entra por parâmetro para este módulo poder ser testado sem arrastar a
    tabela de tipos junto, não para permitir uma segunda definição.
    """
    alinhamento = alinha(esperadas, obtidas)

    por_campo = []
    for campo in campos:
        certos = sum(
            1
            for esperada, obtida in alinhamento.casadas
            if iguais(campo, esperada.campos.get(campo, ""), obtida.campos.get(campo, ""))
        )
        por_campo.append(
            AcuraciaDeCampo(campo=campo, certos=certos, avaliados=len(alinhamento.casadas))
        )

    return MetricasDeLinha(alinhamento=alinhamento, por_campo=tuple(por_campo))


def agrega(medidas: Sequence[MetricasDeLinha]) -> MetricasDeLinha:
    """Soma as medidas de vários quadros num número por documento.

    Soma contagens, nunca médias de taxas: a média das taxas de um quadro de
    quarenta linhas com a de um quadro de uma daria o mesmo peso às duas.
    """
    alinhamento = Alinhamento(
        casadas=tuple(par for m in medidas for par in m.alinhamento.casadas),
        faltantes=tuple(linha for m in medidas for linha in m.alinhamento.faltantes),
        inventadas=tuple(linha for m in medidas for linha in m.alinhamento.inventadas),
        repetidas=tuple(chave for m in medidas for chave in m.alinhamento.repetidas),
    )

    nomes: list[str] = []
    for medida in medidas:
        for campo in medida.por_campo:
            if campo.campo not in nomes:
                nomes.append(campo.campo)

    por_campo = tuple(
        AcuraciaDeCampo(
            campo=nome,
            certos=sum(c.certos for m in medidas for c in m.por_campo if c.campo == nome),
            avaliados=sum(c.avaliados for m in medidas for c in m.por_campo if c.campo == nome),
        )
        for nome in nomes
    )
    return MetricasDeLinha(alinhamento=alinhamento, por_campo=por_campo)
