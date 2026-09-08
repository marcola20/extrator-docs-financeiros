"""O pipeline do informe, de um par de PDFs a duas decisões.

Mesma ordem e mesma razão do pipeline de boleto: sanitização e ingestão são
locais e baratas, extração custa cota, e a segunda execução custa outra. Nada
aqui decide o que um sinal significa — isso é de `app.confianca.politica_informe`.

## Por que a unidade é o par, e não o documento

O sinal mais forte desta fase não cabe num documento só. O informe do ano N
declara o saldo de 31/12/N-1, e quem o desmente é o informe de N-1, que afirma
o mesmo saldo por conta própria (ADR 007). Um pipeline que processasse um
documento por vez teria de escolher entre duas coisas ruins: nunca cruzar, ou
extrair o par de novo a cada documento — e aí cada PDF do corpus seria extraído
duas vezes, dobrando a cota.

Então o processamento tem duas fases explícitas:

1. **Por documento** — ingestão, sanitização, extração, grounding, aritmética
   de quadro e auto-consistência. É aqui que a cota é gasta, e cada documento
   passa por ela **uma vez**. Custo, latência e número de chamadas são desta
   fase, e por isso não contam nada duas vezes.
2. **Por par** — o cruzamento entre anos e a decisão final de cada um dos dois.
   Função pura: não chama modelo, não abre arquivo.

Quem é o informe do ano e quem é o do ano anterior sai do próprio dado
extraído, não de um gabarito: é o `ano_calendario` que o modelo leu. Se os dois
não formarem anos consecutivos, `cruza` devolve `ANOS_NAO_CONSECUTIVOS`, o
sinal sai sem cobertura, e os dois documentos vão para revisão — que é a
resposta certa para "não deu para conferir".

## O que dispara a segunda execução

No modo condicional, o mesmo critério do boleto: **algum sinal reprovou**.
Quadro sem total impresso não entra nesse critério, embora bloqueie a
auto-aprovação. A razão é orçamento: metade do corpus é comprovante de fonte
pagadora, que nunca tem total, e nunca será auto-aprovado por causa disso —
gastar uma segunda chamada em cada um deles dobraria a cota sem mudar decisão
nenhuma.
"""

import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.confianca import consistencia as sinal_consistencia
from app.confianca import grounding as sinal_grounding
from app.confianca.consistencia import ModoConsistencia, ResultadoConsistencia
from app.confianca.grounding import ResultadoGrounding
from app.confianca.politica import DecisaoFinal, Rota, Sinal, Veredito
from app.confianca.politica_informe import decide
from app.config import Settings
from app.dominio.cruzamento import ResultadoCruzamento, cruza
from app.extracao.extrator_informe import ExtracaoDeInforme, como_mapa
from app.extracao.extrator_informe import extrai as extrai_informe
from app.extracao.prompt import PROMPT_INFORME, Prompt, carrega
from app.ingestao.documento import DocumentoIngerido
from app.ingestao.leitor import ingere
from app.llm.provedor import ProvedorLLM
from app.seguranca.politica import Decisao as DecisaoDeSanitizacao
from app.seguranca.politica import decide as decide_sanitizacao

GROUNDING_VAZIO = ResultadoGrounding(())

SEM_EXTRACAO = "extração não rodou"


@dataclass(frozen=True, slots=True)
class LeituraDeInforme:
    """O que a primeira fase produziu para um documento, antes de haver par.

    Existe separado de `ResultadoInforme` porque a decisão de um informe
    depende do outro, e o custo não. Manter as duas coisas em tipos distintos
    é o que garante que custo, latência e chamadas sejam contados uma vez só.
    """

    documento: Path
    ingestao: DocumentoIngerido
    sanitizacao: DecisaoDeSanitizacao
    extracao: ExtracaoDeInforme | None
    grounding: ResultadoGrounding
    consistencia: ResultadoConsistencia
    latencia_s: float
    custo_estimado_usd: Decimal
    chamadas_ao_modelo: int
    motivo_de_nao_extrair: str = ""


@dataclass(frozen=True, slots=True)
class ResultadoInforme:
    """Tudo que o processamento de um informe produziu, já com o par cruzado."""

    documento: Path
    ingestao: DocumentoIngerido
    decisao: DecisaoFinal
    extracao: ExtracaoDeInforme | None
    grounding: ResultadoGrounding
    consistencia: ResultadoConsistencia
    cruzamento: ResultadoCruzamento | None
    par: Path | None
    latencia_s: float
    custo_estimado_usd: Decimal
    chamadas_ao_modelo: int

    @property
    def auto_aprovado(self) -> bool:
        return self.decisao.auto_aprovado

    @property
    def teve_cobertura_real(self) -> bool:
        """Algum sinal chegou a conferir alguma coisa neste documento.

        É a pergunta que separa "verificado" de "nada objetou". Ver o ADR 009
        e `DecisaoFinal.so_falta_de_cobertura`.
        """
        conferiram = {Sinal.ARITMETICA, Sinal.CRUZAMENTO}
        return all(
            veredito.executou for veredito in self.decisao.vereditos if veredito.sinal in conferiram
        )


def _decisao_sem_extracao(motivo: str) -> DecisaoFinal:
    """Documento barrado antes de chegar ao modelo."""
    return DecisaoFinal(
        rota=Rota.REVISAO_HUMANA,
        vereditos=(
            Veredito(sinal=Sinal.SANITIZACAO, aprovou=False, executou=True, detalhe=motivo),
        ),
    )


def le(
    caminho: Path,
    provedor: ProvedorLLM,
    settings: Settings,
    *,
    prompt: Prompt | None = None,
    provedor_da_segunda: ProvedorLLM | None = None,
    com_ocr: bool = True,
) -> LeituraDeInforme:
    """Primeira fase: tudo que um documento produz sozinho. É aqui que a cota vai."""
    inicio = time.monotonic()
    usado = prompt if prompt is not None else carrega(PROMPT_INFORME)
    documento = ingere(caminho, com_ocr=com_ocr)
    sanitizacao = decide_sanitizacao(documento.sanitizacao)

    if documento.por_visao:
        # A ingestão abre o caminho de visão; a extração não o atravessa,
        # porque a sanitização da Fase 1.2 não tem cobertura sobre imagem.
        return LeituraDeInforme(
            documento=caminho,
            ingestao=documento,
            sanitizacao=sanitizacao,
            extracao=None,
            grounding=GROUNDING_VAZIO,
            consistencia=sinal_consistencia.falha(SEM_EXTRACAO),
            latencia_s=time.monotonic() - inicio,
            custo_estimado_usd=Decimal("0"),
            chamadas_ao_modelo=0,
            motivo_de_nao_extrair=documento.aviso or "documento sem camada de texto",
        )

    extracao = extrai_informe(documento, provedor, prompt=usado)
    chamadas = 0 if extracao.do_cache else 1
    custo = extracao.custo_estimado_usd
    grounding = sinal_grounding.confere_informe(extracao.bruto, documento.texto)

    ja_falhou = (
        not sanitizacao.auto_aprovavel
        or not extracao.fecha_no_dominio
        or not grounding.aprovado
        or bool(extracao.quadros_divergentes)
    )
    modo = ModoConsistencia(settings.auto_consistencia.strip().lower())
    roda_segunda, motivo = sinal_consistencia.deve_executar(modo, algum_sinal_falhou=ja_falhou)

    if not roda_segunda:
        resultado_consistencia = sinal_consistencia.dispensa(motivo)
    elif provedor_da_segunda is None:
        # O pipeline não constrói provedor: um teste que esquecesse de injetar
        # o segundo faria chamada de rede de verdade. Ver o pipeline de boleto.
        resultado_consistencia = sinal_consistencia.falha(
            "o segundo provedor não foi fornecido; use "
            "consistencia.provedor_para_segunda_execucao no chamador"
        )
    else:
        segunda = extrai_informe(documento, provedor_da_segunda, prompt=usado)
        chamadas += 0 if segunda.do_cache else 1
        custo += segunda.custo_estimado_usd
        resultado_consistencia = sinal_consistencia.compara_mapas(
            como_mapa(extracao.bruto), como_mapa(segunda.bruto)
        )

    return LeituraDeInforme(
        documento=caminho,
        ingestao=documento,
        sanitizacao=sanitizacao,
        extracao=extracao,
        grounding=grounding,
        consistencia=resultado_consistencia,
        latencia_s=time.monotonic() - inicio,
        custo_estimado_usd=custo,
        chamadas_ao_modelo=chamadas,
    )


def cruza_leituras(
    primeira: LeituraDeInforme, segunda: LeituraDeInforme
) -> tuple[ResultadoCruzamento | None, str]:
    """Cruza duas leituras, na ordem que o ano-calendário extraído indicar.

    Devolve `None` com o motivo escrito quando não há o que cruzar: um dos dois
    não fechou no domínio, e sem `Informe` não há saldo confiável para comparar.
    Não fechar já bloqueia por si; aqui a consequência é o cruzamento ficar sem
    cobertura, que também bloqueia — e o relatório mostra os dois.
    """
    a = primeira.extracao.dominio if primeira.extracao else None
    b = segunda.extracao.dominio if segunda.extracao else None
    if a is None or b is None:
        qual = primeira.documento.name if a is None else segunda.documento.name
        return None, f"{qual} não fechou no domínio; sem informe válido não há saldo a cruzar"

    do_ano, do_anterior = (a, b) if a.ano_calendario >= b.ano_calendario else (b, a)
    return cruza(do_ano, do_anterior), ""


def _conclui(
    leitura: LeituraDeInforme,
    cruzamento: ResultadoCruzamento | None,
    motivo_sem_cruzamento: str,
    par: Path | None,
) -> ResultadoInforme:
    """Segunda fase, para um dos dois documentos. Pura."""
    if leitura.extracao is None:
        decisao = _decisao_sem_extracao(leitura.motivo_de_nao_extrair or SEM_EXTRACAO)
    else:
        decisao = decide(
            sanitizacao=leitura.sanitizacao,
            extracao=leitura.extracao,
            grounding=leitura.grounding,
            consistencia=leitura.consistencia,
            cruzamento=cruzamento,
            motivo_sem_cruzamento=motivo_sem_cruzamento,
        )

    return ResultadoInforme(
        documento=leitura.documento,
        ingestao=leitura.ingestao,
        decisao=decisao,
        extracao=leitura.extracao,
        grounding=leitura.grounding,
        consistencia=leitura.consistencia,
        cruzamento=cruzamento,
        par=par,
        latencia_s=leitura.latencia_s,
        custo_estimado_usd=leitura.custo_estimado_usd,
        chamadas_ao_modelo=leitura.chamadas_ao_modelo,
    )


def decide_par(
    primeira: LeituraDeInforme, segunda: LeituraDeInforme
) -> tuple[ResultadoInforme, ResultadoInforme]:
    """Cruza as duas leituras e conclui a decisão de cada uma. Pura."""
    cruzamento, motivo = cruza_leituras(primeira, segunda)
    return (
        _conclui(primeira, cruzamento, motivo, segunda.documento),
        _conclui(segunda, cruzamento, motivo, primeira.documento),
    )


def processa_par(
    primeiro: Path,
    segundo: Path,
    provedor: ProvedorLLM,
    settings: Settings,
    *,
    prompt: Prompt | None = None,
    provedor_da_segunda: ProvedorLLM | None = None,
    com_ocr: bool = True,
) -> tuple[ResultadoInforme, ResultadoInforme]:
    """Processa os dois informes de um par de anos consecutivos, ponta a ponta."""
    leituras = [
        le(
            caminho,
            provedor,
            settings,
            prompt=prompt,
            provedor_da_segunda=provedor_da_segunda,
            com_ocr=com_ocr,
        )
        for caminho in (primeiro, segundo)
    ]
    return decide_par(leituras[0], leituras[1])


def processa(
    caminho: Path,
    provedor: ProvedorLLM,
    settings: Settings,
    *,
    prompt: Prompt | None = None,
    provedor_da_segunda: ProvedorLLM | None = None,
    com_ocr: bool = True,
) -> ResultadoInforme:
    """Processa um informe sem par.

    O cruzamento entre anos não roda, e por isso o documento não é
    auto-aprovável: o sinal não teve o que conferir, e não ter conferido não é
    aprovar. Ver ADR 009.
    """
    leitura = le(
        caminho,
        provedor,
        settings,
        prompt=prompt,
        provedor_da_segunda=provedor_da_segunda,
        com_ocr=com_ocr,
    )
    from app.confianca.politica_informe import SEM_PAR

    return _conclui(leitura, None, SEM_PAR, None)
