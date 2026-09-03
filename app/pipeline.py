"""O pipeline inteiro, de um PDF a uma decisão.

Ingestão → sanitização → extração → três sinais → roteamento. É o único lugar
onde as camadas se encontram; cada uma delas continua testável sozinha.

Nada aqui decide o que um sinal significa. A ordem é fixa e a razão é custo:
sanitização e ingestão são locais e baratas, extração custa cota, e a segunda
execução custa outra. Um documento que já foi barrado antes da extração não
gasta chamada nenhuma.
"""

import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.confianca import consistencia as sinal_consistencia
from app.confianca import grounding as sinal_grounding
from app.confianca.consistencia import ModoConsistencia, ResultadoConsistencia
from app.confianca.grounding import ResultadoGrounding
from app.confianca.politica import DecisaoFinal, Rota, Sinal, Veredito, decide
from app.config import Settings
from app.extracao.extrator import Extracao, extrai
from app.extracao.prompt import Prompt, carrega
from app.ingestao.documento import DocumentoIngerido
from app.ingestao.leitor import ingere
from app.llm.provedor import ProvedorLLM
from app.seguranca.politica import decide as decide_sanitizacao

GROUNDING_VAZIO = ResultadoGrounding(())


@dataclass(frozen=True, slots=True)
class ResultadoPipeline:
    """Tudo que o processamento de um documento produziu."""

    documento: Path
    ingestao: DocumentoIngerido
    decisao: DecisaoFinal
    extracao: Extracao | None
    grounding: ResultadoGrounding
    consistencia: ResultadoConsistencia
    latencia_s: float
    custo_estimado_usd: Decimal
    chamadas_ao_modelo: int

    @property
    def auto_aprovado(self) -> bool:
        return self.decisao.auto_aprovado


def _decisao_sem_extracao(motivo: str) -> DecisaoFinal:
    """Documento barrado antes de chegar ao modelo."""
    return DecisaoFinal(
        rota=Rota.REVISAO_HUMANA,
        vereditos=(
            Veredito(
                sinal=Sinal.SANITIZACAO,
                aprovou=False,
                executou=True,
                detalhe=motivo,
            ),
        ),
    )


def processa(
    caminho: Path,
    provedor: ProvedorLLM,
    settings: Settings,
    *,
    prompt: Prompt | None = None,
    provedor_da_segunda: ProvedorLLM | None = None,
    com_ocr: bool = True,
) -> ResultadoPipeline:
    """Processa um documento de ponta a ponta."""
    inicio = time.monotonic()
    usado = prompt if prompt is not None else carrega()
    documento = ingere(caminho, com_ocr=com_ocr)

    if documento.por_visao:
        # A ingestão abre o caminho de visão; a extração não o atravessa,
        # porque a sanitização da Fase 1.2 não tem cobertura sobre imagem.
        return ResultadoPipeline(
            documento=caminho,
            ingestao=documento,
            decisao=_decisao_sem_extracao(documento.aviso or "documento sem camada de texto"),
            extracao=None,
            grounding=GROUNDING_VAZIO,
            consistencia=sinal_consistencia.falha("extração não rodou"),
            latencia_s=time.monotonic() - inicio,
            custo_estimado_usd=Decimal("0"),
            chamadas_ao_modelo=0,
        )

    extracao = extrai(documento, provedor, prompt=usado)
    chamadas = 0 if extracao.do_cache else 1
    custo = extracao.custo_estimado_usd

    grounding = sinal_grounding.confere(extracao.bruto, documento.texto)
    decisao_sanitizacao = decide_sanitizacao(documento.sanitizacao)

    ja_falhou = (
        not decisao_sanitizacao.auto_aprovavel
        or not extracao.fecha_no_dominio
        or not grounding.aprovado
    )
    modo = ModoConsistencia(settings.auto_consistencia.strip().lower())
    roda_segunda, motivo = sinal_consistencia.deve_executar(modo, algum_sinal_falhou=ja_falhou)

    if not roda_segunda:
        resultado_consistencia = sinal_consistencia.dispensa(motivo)
    elif provedor_da_segunda is None:
        # O pipeline não constrói provedor. Se construísse, um teste que
        # esquecesse de injetar o segundo faria chamada de rede de verdade —
        # aconteceu uma vez aqui. Quem monta provedor é o eval, e este
        # caminho vira sinal que falhou, que bloqueia.
        resultado_consistencia = sinal_consistencia.falha(
            "o segundo provedor não foi fornecido; use "
            "consistencia.provedor_para_segunda_execucao no chamador"
        )
    else:
        segunda = extrai(documento, provedor_da_segunda, prompt=usado)
        chamadas += 0 if segunda.do_cache else 1
        custo += segunda.custo_estimado_usd
        resultado_consistencia = sinal_consistencia.compara(extracao.bruto, segunda.bruto)

    return ResultadoPipeline(
        documento=caminho,
        ingestao=documento,
        decisao=decide(
            sanitizacao=decisao_sanitizacao,
            extracao=extracao,
            grounding=grounding,
            consistencia=resultado_consistencia,
        ),
        extracao=extracao,
        grounding=grounding,
        consistencia=resultado_consistencia,
        latencia_s=time.monotonic() - inicio,
        custo_estimado_usd=custo,
        chamadas_ao_modelo=chamadas,
    )
