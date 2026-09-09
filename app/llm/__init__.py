"""Fábrica do provedor de LLM.

É aqui que a escolha do ambiente vira objeto. Quem extrai pede um
`ProvedorLLM` e não sabe se por trás está Gemini ou Anthropic, nem que existe
cache e limitador no caminho — ver ADR 003.

A composição é deliberada: `ProvedorComCotaECache` é um decorador que
implementa o mesmo `ProvedorLLM` que envolve. Cache e cota são política de
uso, não parte do contrato de extração, e por isso ficam fora do Protocol.
"""

from dataclasses import dataclass

from pydantic import BaseModel

from app.config import Settings, get_settings
from app.llm import anthropic as modulo_anthropic
from app.llm import gemini as modulo_gemini
from app.llm.anthropic import ProvedorAnthropic
from app.llm.cache import CacheDeExtracao
from app.llm.gemini import ProvedorGemini
from app.llm.limitador import Cota, LimitadorDeTaxa
from app.llm.provedor import (
    INSTRUCAO_PADRAO,
    ErroDeConfiguracao,
    ProvedorLLM,
    ResultadoExtracao,
)

__all__ = [
    "CacheDeExtracao",
    "Cota",
    "ErroDeConfiguracao",
    "LimitadorDeTaxa",
    "ProvedorComCotaECache",
    "ProvedorLLM",
    "ResultadoExtracao",
    "cria_provedor",
]


@dataclass(frozen=True)
class ProvedorComCotaECache:
    """Um `ProvedorLLM` que consulta o cache antes e respeita a cota depois.

    A ordem importa: o cache vem primeiro porque um acerto não consome cota
    nenhuma — é justamente o ponto de ter cache num tier gratuito.
    """

    base: ProvedorLLM
    limitador: LimitadorDeTaxa
    cache: CacheDeExtracao

    @property
    def nome(self) -> str:
        return self.base.nome

    @property
    def modelo(self) -> str:
        return self.base.modelo

    def extrai[TSchema: BaseModel](
        self,
        texto: str,
        schema: type[TSchema],
        *,
        instrucao: str = INSTRUCAO_PADRAO,
    ) -> ResultadoExtracao[TSchema]:
        chave = self.cache.chave(self.base.nome, self.base.modelo, instrucao, texto)

        guardado = self.cache.le(chave, schema)
        if guardado is not None:
            return guardado

        resultado = self.limitador.executa(
            lambda: self.base.extrai(texto, schema, instrucao=instrucao)
        )
        self.cache.grava(chave, resultado)
        return resultado


def _constroi_gemini(settings: Settings) -> tuple[ProvedorLLM, Cota]:
    modelo = settings.llm_modelo or modulo_gemini.MODELO_PADRAO
    provedor = ProvedorGemini(settings.gemini_api_key.get_secret_value(), modelo)
    cota = modulo_gemini.COTAS_TIER_GRATUITO.get(modelo, Cota(rpm=5, rpd=20))
    return provedor, cota


def _constroi_anthropic(settings: Settings) -> tuple[ProvedorLLM, Cota]:
    modelo = settings.llm_modelo or modulo_anthropic.MODELO_PADRAO
    provedor = ProvedorAnthropic(settings.anthropic_api_key.get_secret_value(), modelo)
    return provedor, modulo_anthropic.COTA_PADRAO


CONSTRUTORES = {
    modulo_gemini.NOME: _constroi_gemini,
    modulo_anthropic.NOME: _constroi_anthropic,
}


def cria_provedor(
    settings: Settings | None = None,
    *,
    cache: CacheDeExtracao | None = None,
) -> ProvedorLLM:
    """Monta o provedor descrito por LLM_PROVEDOR e LLM_MODELO.

    Levanta `ErroDeConfiguracao` com o nome da variável a corrigir quando o
    provedor é desconhecido ou a chave dele está faltando.
    """
    settings = settings if settings is not None else get_settings()

    if settings.llm_sem_rede:
        raise ErroDeConfiguracao(
            "LLM_SEM_REDE está ligado: este ambiente não fala com o provedor. "
            "É o modo do CI, onde nenhum job chama o modelo — se você chegou "
            "aqui num teste, ele precisa receber um provedor de mentira em vez "
            "de deixar a fábrica montar um de verdade."
        )

    nome = settings.llm_provedor.strip().lower()
    construtor = CONSTRUTORES.get(nome)
    if construtor is None:
        conhecidos = ", ".join(sorted(CONSTRUTORES))
        raise ErroDeConfiguracao(
            f"LLM_PROVEDOR={settings.llm_provedor!r} não existe; use um de: {conhecidos}"
        )

    base, cota_de_tabela = construtor(settings)
    cota = Cota(
        rpm=settings.llm_rpm or cota_de_tabela.rpm,
        rpd=settings.llm_rpd or cota_de_tabela.rpd,
    )

    return ProvedorComCotaECache(
        base=base,
        limitador=LimitadorDeTaxa(f"{base.nome}:{base.modelo}", cota, settings.llm_arquivo_cotas),
        cache=cache
        if cache is not None
        else CacheDeExtracao(
            diretorio=settings.llm_cache_diretorio,
            ativo=settings.llm_cache_ativo,
        ),
    )
