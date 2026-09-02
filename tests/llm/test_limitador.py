"""Limitador de taxa: RPM espera, RPD bloqueia, 429 volta com backoff."""

from datetime import date
from pathlib import Path

import pytest

from app.llm.limitador import (
    JANELA_RPM_S,
    Cota,
    CotaDiariaExcedida,
    LimitadorDeTaxa,
)
from app.llm.provedor import ErroDeTaxa
from tests.llm.falso import RelogioFalso

HOJE = date(2026, 9, 2)
AMANHA = date(2026, 9, 3)


def _limitador(
    arquivo: Path,
    cota: Cota,
    relogio: RelogioFalso,
    *,
    dia: date = HOJE,
    tentativas: int = 5,
) -> LimitadorDeTaxa:
    return LimitadorDeTaxa(
        "falso:falso-1",
        cota,
        arquivo,
        tentativas=tentativas,
        agora=relogio.agora,
        hoje=lambda: dia,
        dorme=relogio.dorme,
    )


def test_cota_tem_que_ser_positiva() -> None:
    with pytest.raises(ValueError, match="positiva"):
        Cota(rpm=0, rpd=10)


def test_dentro_do_rpm_nao_espera(tmp_path: Path) -> None:
    relogio = RelogioFalso()
    limitador = _limitador(tmp_path / "cotas.json", Cota(rpm=3, rpd=100), relogio)

    for _ in range(3):
        limitador.executa(lambda: "ok")

    assert relogio.dormidas == []


def test_estourar_o_rpm_espera_a_janela_deslizar(tmp_path: Path) -> None:
    relogio = RelogioFalso()
    limitador = _limitador(tmp_path / "cotas.json", Cota(rpm=2, rpd=100), relogio)

    limitador.executa(lambda: "ok")
    limitador.executa(lambda: "ok")
    relogio.avanca(10.0)
    limitador.executa(lambda: "ok")

    # A terceira chamada esperou o resto do minuto da primeira.
    assert relogio.dormidas == [JANELA_RPM_S - 10.0]


def test_estourar_o_rpd_bloqueia_em_vez_de_esperar(tmp_path: Path) -> None:
    """Esperar a virada do dia não é opção: quem chamou decide o que fazer."""
    relogio = RelogioFalso()
    limitador = _limitador(tmp_path / "cotas.json", Cota(rpm=100, rpd=2), relogio)

    limitador.executa(lambda: "ok")
    limitador.executa(lambda: "ok")

    with pytest.raises(CotaDiariaExcedida, match="zera na virada do dia"):
        limitador.executa(lambda: "ok")

    assert relogio.dormidas == []


def test_contador_diario_sobrevive_a_reinicio_do_processo(tmp_path: Path) -> None:
    arquivo = tmp_path / "cotas.json"
    cota = Cota(rpm=100, rpd=2)

    primeiro = _limitador(arquivo, cota, RelogioFalso())
    primeiro.executa(lambda: "ok")

    # Instância nova, mesmo arquivo: é o que acontece ao reiniciar o processo.
    segundo = _limitador(arquivo, cota, RelogioFalso())
    assert segundo.restante_hoje() == 1
    segundo.executa(lambda: "ok")

    with pytest.raises(CotaDiariaExcedida):
        segundo.executa(lambda: "ok")


def test_a_virada_do_dia_zera_o_contador(tmp_path: Path) -> None:
    arquivo = tmp_path / "cotas.json"
    cota = Cota(rpm=100, rpd=1)

    hoje = _limitador(arquivo, cota, RelogioFalso(), dia=HOJE)
    hoje.executa(lambda: "ok")
    with pytest.raises(CotaDiariaExcedida):
        hoje.executa(lambda: "ok")

    amanha = _limitador(arquivo, cota, RelogioFalso(), dia=AMANHA)

    assert amanha.restante_hoje() == 1
    assert amanha.executa(lambda: "ok") == "ok"


def test_estado_corrompido_nao_trava_o_pipeline(tmp_path: Path) -> None:
    arquivo = tmp_path / "cotas.json"
    arquivo.write_text("{quebrado", encoding="utf-8")
    limitador = _limitador(arquivo, Cota(rpm=10, rpd=10), RelogioFalso())

    assert limitador.executa(lambda: "ok") == "ok"


def test_429_volta_com_backoff_exponencial(tmp_path: Path) -> None:
    relogio = RelogioFalso()
    limitador = _limitador(tmp_path / "cotas.json", Cota(rpm=100, rpd=100), relogio)
    falhas = [ErroDeTaxa("429"), ErroDeTaxa("429")]

    def chamada() -> str:
        if falhas:
            raise falhas.pop(0)
        return "ok"

    assert limitador.executa(chamada) == "ok"
    assert relogio.dormidas == [2.0, 4.0]


def test_429_respeita_a_espera_sugerida_pelo_provedor(tmp_path: Path) -> None:
    relogio = RelogioFalso()
    limitador = _limitador(tmp_path / "cotas.json", Cota(rpm=100, rpd=100), relogio)
    falhas = [ErroDeTaxa("429", espera_sugerida_s=30.0)]

    def chamada() -> str:
        if falhas:
            raise falhas.pop(0)
        return "ok"

    limitador.executa(chamada)

    assert relogio.dormidas == [30.0]


def test_429_sem_fim_repropaga_depois_das_tentativas(tmp_path: Path) -> None:
    relogio = RelogioFalso()
    limitador = _limitador(tmp_path / "cotas.json", Cota(rpm=100, rpd=100), relogio, tentativas=3)

    def chamada() -> str:
        raise ErroDeTaxa("429 sempre")

    with pytest.raises(ErroDeTaxa, match="sempre"):
        limitador.executa(chamada)

    assert len(relogio.dormidas) == 2


def test_repetir_por_429_consome_cota_diaria(tmp_path: Path) -> None:
    """O provedor conta a requisição recusada, então o contador local também."""
    relogio = RelogioFalso()
    limitador = _limitador(tmp_path / "cotas.json", Cota(rpm=100, rpd=5), relogio, tentativas=3)

    def chamada() -> str:
        raise ErroDeTaxa("429 sempre")

    with pytest.raises(ErroDeTaxa):
        limitador.executa(chamada)

    assert limitador.restante_hoje() == 2
