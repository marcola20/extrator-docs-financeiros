"""Observabilidade: liga quando há chave, e não acontece nada quando não há.

É a propriedade que permite este módulo existir sem mexer no resto — o eval
processa 56 documentos e não pode passar a depender de um serviço.
"""

from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr

from app import observabilidade
from app.config import Settings


class TestDesligadoPorPadrao:
    def test_sem_chave_o_observador_e_mudo(self) -> None:
        assert not observabilidade.observador(Settings(_env_file=None)).ativo

    def test_o_trecho_mudo_aceita_tudo_e_nao_faz_nada(self) -> None:
        observador = observabilidade.observador(Settings(_env_file=None))

        with observador.trecho("documento", documento="boleto-001.pdf") as trecho:
            trecho.anota(custo_usd=Decimal("0.0005"), sinais={"dominio": "conferido"})

        observador.descarrega()

    def test_observar_nao_muda_resultado_nenhum(self) -> None:
        """Ligar observabilidade não pode alterar extração; senão os relatórios
        deixariam de ser comparáveis entre um ambiente e outro."""
        observador = observabilidade.observador(Settings(_env_file=None))
        resultado = []

        with observador.trecho("documento") as trecho:
            trecho.anota(qualquer="coisa")
            resultado.append("processado")

        assert resultado == ["processado"]


class ClienteQueQuebra:
    """Um Langfuse que falha em tudo. É o cenário que não pode derrubar nada."""

    def start_as_current_span(self, **_: Any) -> Any:
        raise RuntimeError("langfuse fora do ar")

    def flush(self) -> None:
        raise RuntimeError("langfuse fora do ar")


class SpanFalso:
    def __init__(self) -> None:
        self.metadados: list[dict[str, Any]] = []

    def update(self, **campos: Any) -> None:
        self.metadados.append(campos)


class GerenciadorFalso:
    def __init__(self, span: SpanFalso) -> None:
        self._span = span
        self.fechado = False

    def __enter__(self) -> SpanFalso:
        return self._span

    def __exit__(self, *_: Any) -> None:
        self.fechado = True


class ClienteFalso:
    def __init__(self) -> None:
        self.span = SpanFalso()
        self.gerenciador = GerenciadorFalso(self.span)
        self.entradas: list[dict[str, Any]] = []
        self.descarregado = 0

    def start_as_current_span(self, **campos: Any) -> GerenciadorFalso:
        self.entradas.append(campos)
        return self.gerenciador

    def flush(self) -> None:
        self.descarregado += 1


class TestLigado:
    def test_abre_um_trecho_com_o_que_identifica_a_execucao(self) -> None:
        """Comparar traces sem saber qual prompt produziu cada um mede pouco."""
        cliente = ClienteFalso()
        observador = observabilidade.ObservadorLangfuse(cliente)

        with observabilidade.observa_documento(
            observador,
            documento="informe-002.pdf",
            tipo="informe",
            prompt="informe-v1+44161a56",
            modelo="gemini-3.5-flash-lite",
            provedor="gemini",
        ):
            pass

        entrada = cliente.entradas[0]["input"]

        assert entrada["prompt"] == "informe-v1+44161a56"
        assert entrada["modelo"] == "gemini-3.5-flash-lite"
        assert cliente.gerenciador.fechado

    def test_anota_custo_latencia_e_sinais(self) -> None:
        cliente = ClienteFalso()
        observador = observabilidade.ObservadorLangfuse(cliente)

        with observador.trecho("documento") as trecho:
            trecho.anota(
                custo_usd=Decimal("0.003070"),
                latencia_s=2.34,
                sinais={"aritmetica": "sem_cobertura"},
            )

        anotado = cliente.span.metadados[0]["metadata"]

        assert anotado["latencia_s"] == 2.34
        assert anotado["sinais"] == {"aritmetica": "sem_cobertura"}

    def test_decimal_vira_texto_e_nao_float(self) -> None:
        """Converter dinheiro para float aqui reintroduziria na observabilidade
        o erro que o projeto evita no domínio inteiro."""
        cliente = ClienteFalso()

        with observabilidade.ObservadorLangfuse(cliente).trecho("t") as trecho:
            trecho.anota(custo_usd=Decimal("0.003070"))

        anotado = cliente.span.metadados[0]["metadata"]["custo_usd"]

        assert anotado == "0.003070"
        assert isinstance(anotado, str)

    def test_decimal_aninhado_tambem(self) -> None:
        cliente = ClienteFalso()

        with observabilidade.ObservadorLangfuse(cliente).trecho("t") as trecho:
            trecho.anota(uso={"custo": Decimal("1.50"), "tokens": [1, 2]})

        assert cliente.span.metadados[0]["metadata"]["uso"]["custo"] == "1.50"


class TestFalhaIsolada:
    """Um trace que quebra nunca derruba a requisição."""

    def test_cliente_quebrado_nao_levanta(self) -> None:
        observador = observabilidade.ObservadorLangfuse(ClienteQueQuebra())

        with observador.trecho("documento", documento="x.pdf") as trecho:
            trecho.anota(custo_usd=Decimal("1"))

        observador.descarrega()

    def test_o_trabalho_acontece_mesmo_com_o_trace_quebrado(self) -> None:
        observador = observabilidade.ObservadorLangfuse(ClienteQueQuebra())
        feito = []

        with observador.trecho("documento"):
            feito.append("extraiu")

        assert feito == ["extraiu"]

    def test_chave_invalida_nao_impede_o_processo_de_subir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ambiente sem Langfuse é o normal, não um defeito."""

        def explode(**_: Any) -> Any:
            raise RuntimeError("host inalcançável")

        import langfuse

        monkeypatch.setattr(langfuse, "Langfuse", explode)

        observador = observabilidade.observador(
            Settings(
                _env_file=None,
                langfuse_public_key=SecretStr("pk-teste"),
                langfuse_secret_key=SecretStr("sk-teste"),
            )
        )

        assert isinstance(observador, observabilidade.ObservadorMudo)


class TestConfiguracao:
    def test_as_chaves_sao_secretas(self) -> None:
        configuracao = Settings(_env_file=None, langfuse_secret_key=SecretStr("sk-secreta"))

        assert "sk-secreta" not in repr(configuracao)
