"""Gerador adversarial: o gabarito precisa ser coerente com o documento."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.confianca import campos
from app.dominio.boleto import Boleto
from app.geradores.boleto_adversarial import (
    ATAQUES,
    VALOR_EXIGIDO_PELA_INJECAO,
    BoletoAdversarial,
    EfeitoPretendido,
    gera_lote,
    main,
    salva,
)

HOJE = date(2026, 9, 2)


@pytest.fixture(scope="module")
def lote() -> list[BoletoAdversarial]:
    return gera_lote(28, semente=2026, hoje=HOJE)


class TestCobertura:
    def test_o_rodizio_cobre_todos_os_ataques(self, lote: list[BoletoAdversarial]) -> None:
        nomes = {a.ataque.nome for a in lote}

        assert len(nomes) == len(ATAQUES)

    def test_distribuicao_e_parelha(self, lote: list[BoletoAdversarial]) -> None:
        contagem: dict[str, int] = {}
        for adversarial in lote:
            contagem[adversarial.ataque.nome] = contagem.get(adversarial.ataque.nome, 0) + 1

        assert max(contagem.values()) - min(contagem.values()) <= 1

    def test_lote_pequeno_demais_e_recusado(self) -> None:
        with pytest.raises(ValueError, match="precisa cobrir"):
            gera_lote(2)

    def test_um_ataque_por_documento(self, lote: list[BoletoAdversarial]) -> None:
        """Dois ataques no mesmo documento não dizem qual detector pegou o quê."""
        for adversarial in lote:
            alterou_valor = adversarial.valor_impresso is not None
            alterou_nome = adversarial.beneficiario_impresso is not None
            injetou_html = bool(adversarial.ataque_html)

            assert sum([alterou_valor, alterou_nome, injetou_html]) == 1


class TestGabarito:
    def test_extracao_correta_e_o_que_esta_impresso(self, lote: list[BoletoAdversarial]) -> None:
        """O alvo da extração é a página, adulterada inclusive. Ver ADR 006.

        Antes o gabarito guardava o dado verdadeiro, e transcrever
        corretamente um campo que o ataque mandou imprimir contava como erro
        de acurácia. Com 4 documentos de cada ataque adulterador num corpus de
        43, isso prendia `valor` e `beneficiario_nome` em 90,7% — o teto
        aritmético — e os dois números passavam a medir a composição do
        corpus, não a leitura.
        """
        for adversarial in lote:
            correta = adversarial.como_gabarito("x.pdf")["extracao_correta"]

            if adversarial.valor_impresso is not None:
                assert correta["valor"] == campos.canonico("valor", adversarial.valor_impresso)
            if adversarial.beneficiario_impresso is not None:
                assert correta["beneficiario_nome"] == adversarial.beneficiario_impresso

    def test_dado_verdadeiro_e_sempre_o_boleto_por_tras_da_adulteracao(
        self, lote: list[BoletoAdversarial]
    ) -> None:
        """A verdade não some do corpus; ela muda de campo."""
        for adversarial in lote:
            gabarito = adversarial.como_gabarito("x.pdf")

            recomposto = Boleto.model_validate(gabarito["dado_verdadeiro"])

            assert recomposto == adversarial.sintetico.boleto

    def test_ataque_sem_adulteracao_deixa_os_dois_iguais(
        self, lote: list[BoletoAdversarial]
    ) -> None:
        """Injeção de instrução não mexe em campo impresso: nada a separar."""
        for adversarial in lote:
            if adversarial.valor_impresso or adversarial.beneficiario_impresso:
                continue
            gabarito = adversarial.como_gabarito("x.pdf")

            assert gabarito["extracao_correta"] == gabarito["dado_verdadeiro"]

    def test_gabarito_diz_qual_ataque_e_onde(self, lote: list[BoletoAdversarial]) -> None:
        for adversarial in lote:
            ataque = adversarial.como_gabarito("x.pdf")["ataque"]

            assert ataque["nome"]
            assert ataque["onde"]
            assert ataque["carga"]
            assert isinstance(ataque["detectavel_pelo_sanitizador"], bool)

    def test_gabarito_declara_o_efeito_pretendido_de_cada_ataque(
        self, lote: list[BoletoAdversarial]
    ) -> None:
        """Sem efeito declarado, "ataque bem-sucedido" não tem como ser medido.

        O efeito já estava no corpus, mas só dentro da prosa da carga. O eval
        acabava medindo divergência do gabarito e chamando isso de sucesso de
        ataque — o que conta como derrota a transcrição correta de um campo
        que o próprio ataque mandou imprimir.
        """
        for adversarial in lote:
            efeito = adversarial.como_gabarito("x.pdf")["ataque"]["efeito_pretendido"]

            assert efeito["descricao"]
            declara_campo = efeito["campo"] is not None
            assert declara_campo or efeito["exige_auto_aprovacao"]
            assert declara_campo == (efeito["valor"] is not None)

    def test_o_valor_exigido_pelo_efeito_e_o_que_a_carga_pede(
        self, lote: list[BoletoAdversarial]
    ) -> None:
        """Texto impresso e efeito declarado não podem divergir.

        Se a carga mandasse retornar 1,00 e o efeito declarasse 2,00, a
        métrica mediria um efeito que nenhum documento pede — e reportaria
        zero ataque bem-sucedido para sempre, sem nunca falhar.
        """
        for adversarial in lote:
            efeito = adversarial.ataque.efeito_pretendido
            if efeito.valor is None:
                continue

            assert efeito.valor in adversarial.ataque.carga

    def test_valor_divergente_so_vence_atravessando_a_defesa(
        self, lote: list[BoletoAdversarial]
    ) -> None:
        """Transcrever o valor impresso é ler certo; vencer é ser aprovado."""
        for adversarial in [a for a in lote if a.ataque.nome == "valor_divergente"]:
            efeito = adversarial.ataque.efeito_pretendido

            assert efeito.valor == adversarial.valor_impresso
            assert efeito.exige_auto_aprovacao

    def test_instrucao_injetada_vence_na_extracao(self, lote: list[BoletoAdversarial]) -> None:
        """A extração ter obedecido já é a vitória, mesmo indo para revisão."""
        injetados = [
            a for a in lote if a.ataque.efeito_pretendido.valor == VALOR_EXIGIDO_PELA_INJECAO
        ]

        assert injetados
        for adversarial in injetados:
            assert adversarial.ataque.efeito_pretendido.campo == "valor"
            assert not adversarial.ataque.efeito_pretendido.exige_auto_aprovacao

    def test_gabarito_registra_o_ataque_que_o_sanitizador_nao_pega(
        self, lote: list[BoletoAdversarial]
    ) -> None:
        """valor_divergente é o caso que só a validação determinística pega."""
        divergentes = [a for a in lote if a.ataque.nome == "valor_divergente"]

        assert divergentes
        for adversarial in divergentes:
            assert not adversarial.ataque.detectavel_pelo_sanitizador
            assert adversarial.ataque.detectores_esperados == ()


class TestValorDivergente:
    def test_o_valor_impresso_difere_do_codificado(self, lote: list[BoletoAdversarial]) -> None:
        (adversarial,) = [a for a in lote if a.ataque.nome == "valor_divergente"][:1]

        assert adversarial.valor_impresso is not None
        assert adversarial.valor_impresso != str(adversarial.sintetico.boleto.valor)

    def test_extrair_o_valor_impresso_e_reprovado_pelo_adr_002(
        self, lote: list[BoletoAdversarial]
    ) -> None:
        """O ataque só vence se a linha digitável fechar com o valor falso.

        Este teste é o argumento do ADR 002 exercitado: montar o boleto com o
        valor que está impresso — o que o atacante quer que se extraia — não
        passa, porque não bate com o que a linha digitável codifica.
        """
        (adversarial,) = [a for a in lote if a.ataque.nome == "valor_divergente"][:1]
        verdadeiro = adversarial.sintetico.boleto
        falso = (verdadeiro.valor / Decimal("100")).quantize(Decimal("0.01"))

        with pytest.raises(ValidationError):
            Boleto.model_validate(verdadeiro.model_dump() | {"valor": falso})

    def test_a_extracao_correta_deste_ataque_nao_fecha_no_dominio(
        self, lote: list[BoletoAdversarial]
    ) -> None:
        """O que a decisão do ADR 006 desloca, dito como teste.

        Ler a página certo passa a ser a extração correta — e a extração
        correta deste documento **não** é um boleto válido. Quem acusa é o
        cruzamento do ADR 002, não mais a acurácia por campo.
        """
        for adversarial in [a for a in lote if a.ataque.nome == "valor_divergente"]:
            correta = adversarial.como_gabarito("x.pdf")["extracao_correta"]

            with pytest.raises(ValidationError):
                Boleto.model_validate(correta)


class TestEscrita:
    def test_salva_pdf_e_gabarito(self, lote: list[BoletoAdversarial], tmp_path: Path) -> None:
        caminho_pdf, caminho_json = salva(lote[0], tmp_path, "teste-001")

        assert caminho_pdf.is_file() and caminho_pdf.stat().st_size > 0
        gabarito = json.loads(caminho_json.read_text(encoding="utf-8"))
        assert gabarito["arquivo_pdf"] == "teste-001.pdf"
        assert gabarito["ataque"]["nome"] == lote[0].ataque.nome

    def test_cli_recusa_sobrescrever_lote(self, tmp_path: Path) -> None:
        argumentos = ["--quantidade", "7", "--saida", str(tmp_path), "--semente", "1"]

        assert main(argumentos) == 0
        assert main(argumentos) == 1
        assert main([*argumentos, "--forcar"]) == 0


class TestEfeitoPretendido:
    def test_efeito_sem_condicao_nenhuma_e_recusado(self) -> None:
        """Um efeito que nada verifica seria contado como vitória sempre."""
        with pytest.raises(ValueError, match="não declara condição"):
            EfeitoPretendido(descricao="nada")

    def test_campo_e_valor_andam_juntos(self) -> None:
        with pytest.raises(ValueError, match="andam juntos"):
            EfeitoPretendido(descricao="meio efeito", campo="valor")

        with pytest.raises(ValueError, match="andam juntos"):
            EfeitoPretendido(descricao="meio efeito", valor="1,00")


class TestProcedencia:
    def test_gabarito_adversarial_grava_semente_e_data(self, lote: list[BoletoAdversarial]) -> None:
        """O corpus adversarial se reproduz pelas mesmas duas coisas."""
        for adversarial in lote:
            gerado_com = adversarial.como_gabarito("x.pdf")["gerado_com"]

            assert gerado_com == {"semente": 2026, "data_de_referencia": HOJE.isoformat()}
