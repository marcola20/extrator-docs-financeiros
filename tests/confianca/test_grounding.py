"""Sinal 2: presença literal no texto de origem."""

from app.confianca.grounding import CAMPOS_ISENTOS, Situacao, confere
from app.extracao.schema_transporte import BoletoExtraido

TEXTO = (
    "Banco Sicoob 756-0\n"
    "75691.23456 78901.234567 89012.345678 9 12340000311230\n"
    "Beneficiário: Comércio de Materiais Freitas Ltda\n"
    "CNPJ 03.721.465/0001-20\n"
    "Vencimento 19/11/2026    Valor do documento R$ 3.112,30\n"
    "Pagador: Caldeira Participações  29.614.387/0001-58\n"
    "Nosso número 27982745989\n"
)


def _extraido(**campos: str) -> BoletoExtraido:
    base = {
        "linha_digitavel": "7569123456789012345678901234567891234",
        "beneficiario_nome": "Comércio de Materiais Freitas Ltda",
        "beneficiario_cnpj": "03721465000120",
        "pagador_nome": "Caldeira Participações",
        "pagador_cpf_cnpj": "29614387000158",
        "valor": "3112.30",
        "vencimento": "2026-11-19",
        "banco_codigo": "756",
        "banco_nome": "Sicoob",
        "nosso_numero": "27982745989",
    }
    return BoletoExtraido(**(base | campos))


class TestCamposEncontrados:
    def test_extracao_fiel_passa_inteira(self) -> None:
        resultado = confere(_extraido(), TEXTO)

        assert resultado.aprovado
        assert resultado.taxa == 1.0

    def test_valor_em_outro_formato_ainda_conta_como_presente(self) -> None:
        """O texto traz R$ 3.112,30; o modelo devolveu 3112.30."""
        (conferencia,) = [c for c in confere(_extraido(), TEXTO).conferencias if c.campo == "valor"]

        assert conferencia.situacao is Situacao.ENCONTRADO

    def test_data_em_outro_formato_ainda_conta_como_presente(self) -> None:
        (conferencia,) = [
            c for c in confere(_extraido(), TEXTO).conferencias if c.campo == "vencimento"
        ]

        assert conferencia.situacao is Situacao.ENCONTRADO

    def test_linha_digitavel_ignora_a_formatacao_impressa(self) -> None:
        (conferencia,) = [
            c for c in confere(_extraido(), TEXTO).conferencias if c.campo == "linha_digitavel"
        ]

        assert conferencia.situacao is Situacao.ENCONTRADO


class TestAlucinacao:
    def test_valor_inventado_e_acusado(self) -> None:
        resultado = confere(_extraido(valor="1.00"), TEXTO)

        assert not resultado.aprovado
        assert [c.campo for c in resultado.ausentes] == ["valor"]

    def test_cnpj_inventado_e_acusado(self) -> None:
        resultado = confere(_extraido(beneficiario_cnpj="11222333000181"), TEXTO)

        assert "beneficiario_cnpj" in [c.campo for c in resultado.ausentes]

    def test_nome_inventado_e_acusado(self) -> None:
        resultado = confere(_extraido(beneficiario_nome="Outra Empresa SA"), TEXTO)

        assert "beneficiario_nome" in [c.campo for c in resultado.ausentes]


class TestIsencaoEDeclaracao:
    def test_campo_isento_nao_e_aprovado_em_silencio(self) -> None:
        """Sai como ISENTO, com o motivo, e não como ENCONTRADO."""
        (conferencia,) = [
            c for c in confere(_extraido(), TEXTO).conferencias if c.campo == "banco_nome"
        ]

        assert conferencia.situacao is Situacao.ISENTO
        assert conferencia.motivo == CAMPOS_ISENTOS["banco_nome"]

    def test_campo_isento_passa_mesmo_sem_estar_no_texto(self) -> None:
        resultado = confere(_extraido(banco_nome="Nome Que Nao Esta Na Pagina"), TEXTO)

        assert resultado.aprovado

    def test_campo_vazio_nao_conta_como_ausente(self) -> None:
        (conferencia,) = [
            c
            for c in confere(_extraido(nosso_numero=""), TEXTO).conferencias
            if c.campo == "nosso_numero"
        ]

        assert conferencia.situacao is Situacao.VAZIO
        assert not conferencia.reprova

    def test_isento_e_vazio_ficam_fora_da_taxa(self) -> None:
        """A taxa mede o que foi conferido, não o que foi dispensado."""
        resultado = confere(_extraido(nosso_numero=""), TEXTO)

        assert resultado.taxa == 1.0


class TestLimiteConhecido:
    def test_campo_trocado_passa_e_isso_esta_documentado(self) -> None:
        """Grounding pega invenção, não troca de campo — os dois CNPJ estão na página."""
        trocado = _extraido(beneficiario_cnpj="29614387000158")

        assert confere(trocado, TEXTO).aprovado
