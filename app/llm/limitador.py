"""Controle de taxa por provedor: RPM em memória, RPD persistido em disco.

O tier gratuito do Gemini é o orçamento inteiro do projeto (ADR 003), então
estourar a cota não é um contratempo: é o pipeline parado até o dia seguinte.
As duas cotas têm naturezas diferentes e por isso tratamento diferente:

- **RPM** é uma janela deslizante de um minuto. Estourar significa esperar
  alguns segundos, então o limitador espera sozinho e segue.
- **RPD** zera só na virada do dia. Esperar não é opção, então o limitador
  levanta `CotaDiariaExcedida` e devolve a decisão a quem chamou.

O contador diário vive em disco porque o processo reinicia — durante o
desenvolvimento, muitas vezes — e um contador em memória recomeçaria do zero
achando que tem 500 chamadas quando já gastou 400.
"""

import json
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.llm.provedor import ErroDeProvedor, ErroTransitorio

JANELA_RPM_S = 60.0
TENTATIVAS_PADRAO = 5
ESPERA_BASE_S = 2.0
ESPERA_MAXIMA_S = 60.0


class CotaDiariaExcedida(ErroDeProvedor):
    """A cota de requisições por dia acabou. Só a virada do dia resolve."""


@dataclass(frozen=True)
class Cota:
    """Limites do tier em uso, por modelo."""

    rpm: int
    rpd: int

    def __post_init__(self) -> None:
        if self.rpm <= 0 or self.rpd <= 0:
            raise ValueError(f"cota tem que ser positiva: {self.rpm=}, {self.rpd=}")


class LimitadorDeTaxa:
    """Faz uma chamada caber na cota do provedor.

    Não é thread-safe entre processos: o arquivo de estado é lido e escrito
    sem trava de arquivo, então dois processos rodando eval ao mesmo tempo
    podem contar a menos. Dentro de um processo, um `Lock` protege o estado.
    """

    def __init__(
        self,
        chave: str,
        cota: Cota,
        arquivo_estado: Path,
        *,
        tentativas: int = TENTATIVAS_PADRAO,
        espera_base_s: float = ESPERA_BASE_S,
        agora: Callable[[], float] = time.monotonic,
        hoje: Callable[[], date] = date.today,
        dorme: Callable[[float], None] = time.sleep,
    ) -> None:
        self._chave = chave
        self._cota = cota
        self._arquivo_estado = arquivo_estado
        self._tentativas = tentativas
        self._espera_base_s = espera_base_s
        self._agora = agora
        self._hoje = hoje
        self._dorme = dorme
        self._janela: deque[float] = deque()
        self._trava = threading.Lock()

    @property
    def cota(self) -> Cota:
        return self._cota

    def restante_hoje(self) -> int:
        """Quantas chamadas ainda cabem na cota diária."""
        with self._trava:
            return max(0, self._cota.rpd - self._consumo_de_hoje())

    def executa[T](self, chamada: Callable[[], T]) -> T:
        """Roda `chamada` respeitando a cota, repetindo o que for transitório.

        Repete a família `ErroTransitorio` inteira, não só o 429: um 503 do
        provedor sobrecarregado passa em segundos, e sem repetição ele derruba
        o documento como se fosse falha de extração — o que num eval vira
        corpus parcial, não um número pior.

        Levanta `CotaDiariaExcedida` antes de gastar a chamada, e repropaga o
        último `ErroTransitorio` se o backoff esgotar as tentativas.
        """
        ultimo_erro: ErroTransitorio | None = None

        for tentativa in range(self._tentativas):
            if tentativa > 0:
                self._dorme(self._espera_do_backoff(tentativa, ultimo_erro))

            self._espera_vaga_no_minuto()
            # Registrada antes da chamada porque o provedor conta a requisição
            # mesmo quando responde 429 — repetir gasta cota de verdade.
            self._registra_chamada()

            try:
                return chamada()
            except ErroTransitorio as erro:
                ultimo_erro = erro

        assert ultimo_erro is not None
        raise ultimo_erro

    def _espera_do_backoff(self, tentativa: int, erro: ErroTransitorio | None) -> float:
        """Backoff exponencial, ou o que o provedor pediu, o que for maior."""
        exponencial = min(self._espera_base_s * 2.0 ** (tentativa - 1), ESPERA_MAXIMA_S)
        if erro is None or erro.espera_sugerida_s is None:
            return exponencial
        return max(exponencial, erro.espera_sugerida_s)

    def _espera_vaga_no_minuto(self) -> None:
        """Segura a chamada até a janela de um minuto ter espaço."""
        while True:
            agora = self._agora()
            while self._janela and agora - self._janela[0] >= JANELA_RPM_S:
                self._janela.popleft()

            if len(self._janela) < self._cota.rpm:
                self._janela.append(agora)
                return

            self._dorme(JANELA_RPM_S - (agora - self._janela[0]))

    def _registra_chamada(self) -> None:
        with self._trava:
            consumo = self._consumo_de_hoje()
            if consumo >= self._cota.rpd:
                raise CotaDiariaExcedida(
                    f"cota diária de {self._cota.rpd} requisições esgotada para "
                    f"{self._chave}; ela zera na virada do dia"
                )
            self._grava_consumo(consumo + 1)

    def _le_estado(self) -> dict[str, Any]:
        try:
            conteudo = self._arquivo_estado.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            estado = json.loads(conteudo)
        except json.JSONDecodeError:
            # Estado corrompido conta como dia novo. Perder o contador é ruim,
            # mas travar o pipeline por um JSON quebrado é pior.
            return {}
        return estado if isinstance(estado, dict) else {}

    def _consumo_de_hoje(self) -> int:
        entrada = self._le_estado().get(self._chave)
        if not isinstance(entrada, dict) or entrada.get("data") != self._hoje().isoformat():
            return 0
        chamadas = entrada.get("chamadas")
        return chamadas if isinstance(chamadas, int) else 0

    def _grava_consumo(self, chamadas: int) -> None:
        estado = self._le_estado()
        estado[self._chave] = {"data": self._hoje().isoformat(), "chamadas": chamadas}
        self._arquivo_estado.parent.mkdir(parents=True, exist_ok=True)
        temporario = self._arquivo_estado.with_suffix(f".{os.getpid()}.tmp")
        temporario.write_text(json.dumps(estado, indent=2, sort_keys=True), encoding="utf-8")
        # Troca atômica: um Ctrl+C no meio da escrita não deixa o contador pela metade.
        temporario.replace(self._arquivo_estado)
