"""Traces no Langfuse, e um no-op quando ele não está configurado.

Os números já existem: o eval mede custo, latência, versão de prompt, modelo e
o resultado de cada sinal desde a Fase 1.3. O que falta é vê-los **em tempo
real**, por requisição, em vez de só no relatório somado no fim de uma passada.

## Sem chave, não acontece nada

É a propriedade que faz este módulo poder existir sem mexer no resto. Sem
`LANGFUSE_PUBLIC_KEY`, `observador()` devolve um objeto que aceita todas as
chamadas e não faz nenhuma. Assim:

- o eval continua rodando sem serviço nenhum — e ele processa 56 documentos, o
  que faria de qualquer dependência obrigatória um problema de infraestrutura;
- o CI não precisa de Langfuse de pé;
- ligar observabilidade não muda o resultado de extração nenhuma, o que
  importa para os relatórios continuarem comparáveis.

Um trace que falha **nunca** derruba a requisição. Observar é para saber o que
aconteceu; se observar quebrasse o pipeline, o custo de instrumentar seria maior
que o de não ter dado nenhum.
"""

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal
from types import TracebackType
from typing import Any, Protocol

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class Trecho(Protocol):
    """Um trecho de trabalho observado."""

    def anota(self, **campos: Any) -> None: ...

    def __enter__(self) -> "Trecho": ...

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        pilha: TracebackType | None,
    ) -> None: ...


class TrechoMudo:
    """O que se recebe quando não há Langfuse. Aceita tudo, não faz nada."""

    def anota(self, **campos: Any) -> None:
        return None

    def __enter__(self) -> "TrechoMudo":
        return self

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        pilha: TracebackType | None,
    ) -> None:
        return None


class Observador(Protocol):
    @property
    def ativo(self) -> bool:
        """Se há Langfuse por trás. Falso é o padrão, e não é modo degradado."""
        ...

    def trecho(self, nome: str, **entrada: Any) -> Trecho: ...

    def descarrega(self) -> None: ...


class ObservadorMudo:
    """Observabilidade desligada. É o padrão, e não é um modo degradado."""

    @property
    def ativo(self) -> bool:
        return False

    def trecho(self, nome: str, **entrada: Any) -> Trecho:
        return TrechoMudo()

    def descarrega(self) -> None:
        return None


class TrechoDoLangfuse:
    """Um span do Langfuse, com falha isolada.

    Toda chamada ao SDK vai dentro de `try`. Um erro de rede, uma versão do SDK
    com outra assinatura, uma chave revogada — nada disso pode virar exceção no
    caminho de um documento sendo processado.
    """

    def __init__(self, gerenciador: Any, nome: str) -> None:
        self._gerenciador = gerenciador
        self._span: Any = None
        self._nome = nome

    def __enter__(self) -> "TrechoDoLangfuse":
        try:
            self._span = self._gerenciador.__enter__()
        except Exception:  # pragma: no cover - depende do SDK
            logger.debug("langfuse: falha ao abrir o trecho %s", self._nome, exc_info=True)
            self._span = None
        return self

    def anota(self, **campos: Any) -> None:
        if self._span is None:
            return
        try:
            self._span.update(metadata={k: _serializavel(v) for k, v in campos.items()})
        except Exception:  # pragma: no cover - depende do SDK
            logger.debug("langfuse: falha ao anotar %s", self._nome, exc_info=True)

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        pilha: TracebackType | None,
    ) -> None:
        try:
            self._gerenciador.__exit__(tipo, erro, pilha)
        except Exception:  # pragma: no cover - depende do SDK
            logger.debug("langfuse: falha ao fechar o trecho %s", self._nome, exc_info=True)


def _serializavel(valor: Any) -> Any:
    """Decimal não atravessa JSON; nem por isso vira float.

    Dinheiro vai como texto (`"0.003070"`), que preserva a precisão e continua
    legível no painel. Converter para float aqui reintroduziria, na
    observabilidade, o erro que o projeto inteiro evita no domínio.
    """
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, Mapping):
        return {k: _serializavel(v) for k, v in valor.items()}
    if isinstance(valor, list | tuple):
        return [_serializavel(item) for item in valor]
    return valor


class ObservadorLangfuse:
    """Observabilidade ligada. Ver a nota do módulo sobre falha isolada."""

    def __init__(self, cliente: Any) -> None:
        self._cliente = cliente

    @property
    def ativo(self) -> bool:
        return True

    def trecho(self, nome: str, **entrada: Any) -> Trecho:
        try:
            gerenciador = self._cliente.start_as_current_span(
                name=nome, input={k: _serializavel(v) for k, v in entrada.items()}
            )
        except Exception:  # pragma: no cover - depende do SDK
            logger.debug("langfuse: falha ao criar o trecho %s", nome, exc_info=True)
            return TrechoMudo()
        return TrechoDoLangfuse(gerenciador, nome)

    def descarrega(self) -> None:
        try:
            self._cliente.flush()
        except Exception:  # pragma: no cover - depende do SDK
            logger.debug("langfuse: falha ao descarregar", exc_info=True)


def observador(settings: Settings | None = None) -> Observador:
    """O observador configurado, ou o mudo quando não há chave.

    Não levanta. Um ambiente sem Langfuse é o normal, não um defeito.
    """
    settings = settings if settings is not None else get_settings()

    if not settings.langfuse_public_key.get_secret_value():
        return ObservadorMudo()

    try:
        from langfuse import Langfuse
    except ImportError:  # pragma: no cover - langfuse é dependência declarada
        logger.warning("langfuse não instalado; observabilidade desligada")
        return ObservadorMudo()

    try:
        cliente = Langfuse(
            public_key=settings.langfuse_public_key.get_secret_value(),
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            host=settings.langfuse_host,
        )
    except Exception:  # pragma: no cover - depende do SDK
        logger.warning("langfuse: não foi possível conectar; seguindo sem traces", exc_info=True)
        return ObservadorMudo()

    return ObservadorLangfuse(cliente)


@contextmanager
def observa_documento(
    observador_atual: Observador,
    *,
    documento: str,
    tipo: str,
    prompt: str,
    modelo: str,
    provedor: str,
) -> Iterator[Trecho]:
    """O trecho de um documento inteiro, com o que identifica a execução.

    Prompt, modelo e provedor entram na abertura porque comparar dois traces sem
    saber qual prompt produziu cada um mede tão pouco quanto comparar dois evals
    sem o mesmo carimbo — é a razão de o relatório carregá-los desde a Fase 1.3.
    """
    with observador_atual.trecho(
        "documento",
        documento=documento,
        tipo=tipo,
        prompt=prompt,
        modelo=modelo,
        provedor=provedor,
    ) as trecho:
        yield trecho
