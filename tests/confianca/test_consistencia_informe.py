"""Auto-consistência num documento multi-registro: lugar a lugar, não campo a campo."""

from app.confianca import consistencia
from app.extracao.extrator_informe import como_mapa
from app.extracao.schema_transporte_informe import (
    InformeExtraido,
    LinhaExtraida,
    QuadroExtraido,
)


def _com(linhas: list[LinhaExtraida], total: str = "1.500,50") -> InformeExtraido:
    return InformeExtraido(
        layout="instituicao_financeira",
        ano_calendario="2024",
        exercicio="2025",
        rendimentos_exclusivos=QuadroExtraido(linhas=linhas, total_impresso=total),
    )


CDB = LinhaExtraida(identificador="CDB", descricao="Certificado", valor="1.000,00")
FUNDO = LinhaExtraida(identificador="Fundo DI", descricao="Fundo", valor="500,50")


class TestDuasLeiturasIguais:
    def test_concordam(self) -> None:
        resultado = consistencia.compara_mapas(
            como_mapa(_com([CDB, FUNDO])), como_mapa(_com([CDB, FUNDO]))
        )

        assert resultado.concordam
        assert resultado.taxa_de_divergencia == 0.0

    def test_ordem_diferente_das_linhas_nao_e_divergencia(self) -> None:
        """Devolver as linhas trocadas de lugar é ler o documento certo."""
        resultado = consistencia.compara_mapas(
            como_mapa(_com([CDB, FUNDO])), como_mapa(_com([FUNDO, CDB]))
        )

        assert resultado.concordam


class TestLinhaQueSoUmaExecucaoDevolveu:
    def test_linha_a_menos_e_divergencia(self) -> None:
        """Trinta linhas contra vinte e nove não é "concordam nos campos comuns"."""
        resultado = consistencia.compara_mapas(
            como_mapa(_com([CDB, FUNDO])), como_mapa(_com([CDB]))
        )

        assert not resultado.concordam
        assert {d.campo for d in resultado.divergencias} == {
            "rendimentos_exclusivos[Fundo DI].chave",
            "rendimentos_exclusivos[Fundo DI].descricao",
            "rendimentos_exclusivos[Fundo DI].valor",
        }

    def test_o_lado_que_faltou_aparece_em_branco(self) -> None:
        resultado = consistencia.compara_mapas(
            como_mapa(_com([CDB, FUNDO])), como_mapa(_com([CDB]))
        )
        divergencia = next(
            d for d in resultado.divergencias if d.campo.endswith("[Fundo DI].valor")
        )

        assert divergencia.primeira == "500,50"
        assert divergencia.segunda == ""


class TestChaveLidaDiferente:
    def test_errar_a_chave_aparece_dos_dois_lados(self) -> None:
        """A linha certa fica faltando e a de chave errada fica sobrando."""
        outra = LinhaExtraida(
            identificador="CDB 8056747", descricao="Certificado", valor="1.000,00"
        )
        resultado = consistencia.compara_mapas(como_mapa(_com([CDB])), como_mapa(_com([outra])))

        locais = {d.campo for d in resultado.divergencias}

        assert any("[CDB]." in local for local in locais)
        assert any("[CDB 8056747]." in local for local in locais)


class TestDenominadorDaTaxa:
    def test_o_denominador_e_quantos_lugares_o_documento_tem(self) -> None:
        """Dez campos fixos descreveriam o boleto, não um informe de 46 linhas."""
        mapa = como_mapa(_com([CDB, FUNDO]))
        resultado = consistencia.compara_mapas(mapa, mapa)

        assert resultado.campos_comparados == len(mapa)
        assert resultado.campos_comparados > 10

    def test_a_taxa_usa_esse_denominador(self) -> None:
        resultado = consistencia.compara_mapas(
            como_mapa(_com([CDB, FUNDO])), como_mapa(_com([CDB, FUNDO], total="9.999,99"))
        )

        assert resultado.taxa_de_divergencia == 1 / resultado.campos_comparados


class TestBoletoNaoMudou:
    def test_o_denominador_do_boleto_continua_sendo_os_dez_campos(self) -> None:
        assert consistencia.ResultadoConsistencia(executou=True).campos_comparados == 10
