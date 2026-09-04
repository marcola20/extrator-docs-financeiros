"""Alinhamento de linha: os três modos de errar que a acurácia média confunde.

Cada teste aqui encena uma falha que produziria o mesmo número numa média de
campo e pede correção diferente: linha perdida (quadro que quebrou de página),
linha duplicada (bloco repetido), e duas linhas fundidas numa (tabela lida
como parágrafo).
"""

from app.avaliacao.linhas import LinhaMedida, agrega, alinha, mede
from app.confianca.campos import iguais

CAMPOS = ("descricao", "valor")


def _linha(identificador: str, valor: str, descricao: str = "Aplicação") -> LinhaMedida:
    return LinhaMedida(identificador=identificador, campos={"descricao": descricao, "valor": valor})


TRES = (
    _linha("CDB 1234567", "1.000,00"),
    _linha("Fundo DI 7654321", "2.500,50"),
    _linha("Tesouro Selic 9999", "300,00"),
)


class TestCasamentoPerfeito:
    def test_tudo_casa_e_as_tres_metricas_ficam_em_um(self) -> None:
        metricas = mede(TRES, TRES, CAMPOS, iguais)

        assert metricas.recall == 1.0
        assert metricas.precisao == 1.0
        assert metricas.acuracia("valor") == 1.0

    def test_ordem_trocada_nao_penaliza(self) -> None:
        """Devolver na ordem errada é leitura certa; penalizar mediria formatação."""
        metricas = mede(TRES, tuple(reversed(TRES)), CAMPOS, iguais)

        assert metricas.recall == 1.0
        assert metricas.precisao == 1.0

    def test_espaco_e_caixa_na_chave_nao_quebram_o_casamento(self) -> None:
        obtidas = (_linha("cdb  1234567", "1.000,00"),)

        alinhamento = alinha((TRES[0],), obtidas)

        assert len(alinhamento.casadas) == 1

    def test_digito_trocado_na_chave_nao_casa(self) -> None:
        """Normalizar até aqui apagaria a diferença entre duas contas."""
        obtidas = (_linha("CDB 1234568", "1.000,00"),)

        alinhamento = alinha((TRES[0],), obtidas)

        assert alinhamento.casadas == ()
        assert len(alinhamento.faltantes) == 1
        assert len(alinhamento.inventadas) == 1


class TestLinhaPerdida:
    def test_linha_faltando_derruba_o_recall_e_nao_a_precisao(self) -> None:
        """O quadro que quebrou de página e teve a segunda metade ignorada."""
        metricas = mede(TRES, TRES[:2], CAMPOS, iguais)

        assert metricas.recall == 2 / 3
        assert metricas.precisao == 1.0
        assert metricas.acuracia("valor") == 1.0, "as que vieram estavam certas"

    def test_a_linha_perdida_aparece_nomeada(self) -> None:
        alinhamento = alinha(TRES, TRES[:2])

        assert [linha.identificador for linha in alinhamento.faltantes] == ["Tesouro Selic 9999"]


class TestLinhaInventada:
    def test_linha_a_mais_derruba_a_precisao_e_nao_o_recall(self) -> None:
        obtidas = (*TRES, _linha("LCI 5555", "999,00"))

        metricas = mede(TRES, obtidas, CAMPOS, iguais)

        assert metricas.recall == 1.0
        assert metricas.precisao == 3 / 4


class TestLinhaDuplicada:
    def test_linha_repetida_conta_como_inventada(self) -> None:
        """O quadro duplicado do corpus adversarial.

        Sem isto ele sairia com recall e precisão perfeitos: todas as linhas
        do documento apareceram, e todas as devolvidas existem. O que não
        existe é o lançamento acontecer duas vezes.
        """
        obtidas = (*TRES, TRES[0])

        metricas = mede(TRES, obtidas, CAMPOS, iguais)

        assert metricas.recall == 1.0
        assert metricas.precisao == 3 / 4
        assert metricas.alinhamento.repetidas == ("CDB 1234567",)

    def test_quadro_inteiro_duplicado(self) -> None:
        metricas = mede(TRES, (*TRES, *TRES), CAMPOS, iguais)

        assert metricas.recall == 1.0
        assert metricas.precisao == 0.5
        assert len(metricas.alinhamento.repetidas) == 3


class TestLinhasFundidas:
    def test_duas_linhas_lidas_como_uma_perdem_as_duas(self) -> None:
        """Tabela lida como parágrafo: a chave fundida não é nenhuma das duas.

        Recall cai por duas linhas faltando e precisão cai pela linha
        inventada. A acurácia de campo não se mexe, e é isso que separa este
        caso de um erro de leitura de número.
        """
        fundida = _linha("CDB 1234567 Fundo DI 7654321", "3.500,50")

        metricas = mede(TRES, (fundida, TRES[2]), CAMPOS, iguais)

        assert metricas.recall == 1 / 3
        assert metricas.precisao == 1 / 2
        assert metricas.acuracia("valor") == 1.0


class TestErroDeLeituraDeNumero:
    def test_valor_errado_com_alinhamento_perfeito(self) -> None:
        """O caso oposto: a estrutura saiu inteira, o número saiu errado."""
        obtidas = (TRES[0], _linha("Fundo DI 7654321", "2.500,05"), TRES[2])

        metricas = mede(TRES, obtidas, CAMPOS, iguais)

        assert metricas.recall == 1.0
        assert metricas.precisao == 1.0
        assert metricas.acuracia("valor") == 2 / 3

    def test_formatacao_do_valor_nao_conta_como_erro(self) -> None:
        """A igualdade é a do ADR 005: `1000.00` e `1.000,00` são o mesmo valor."""
        obtidas = (_linha("CDB 1234567", "1000.00"),)

        metricas = mede((TRES[0],), obtidas, CAMPOS, iguais)

        assert metricas.acuracia("valor") == 1.0


class TestQuadroVazio:
    def test_nada_esperado_e_nada_devolvido_nao_e_falha(self) -> None:
        metricas = mede((), (), CAMPOS, iguais)

        assert metricas.recall == 1.0
        assert metricas.precisao == 1.0

    def test_nada_esperado_e_algo_devolvido_zera_a_precisao(self) -> None:
        metricas = mede((), (_linha("CDB 1", "10,00"),), CAMPOS, iguais)

        assert metricas.recall == 1.0
        assert metricas.precisao == 0.0

    def test_acuracia_sem_linha_casada_e_zero_com_denominador_zero(self) -> None:
        """Não há como afirmar acerto nenhum; o denominador denuncia."""
        metricas = mede(TRES, (), CAMPOS, iguais)

        assert metricas.acuracia("valor") == 0.0
        assert metricas.por_campo[0].avaliados == 0


class TestAgregacao:
    def test_agrega_soma_contagens_e_nao_media_de_taxas(self) -> None:
        """Um quadro de 40 linhas não pode pesar o mesmo que um de uma."""
        muitas = tuple(_linha(f"CDB {i:04d}", "10,00") for i in range(40))
        erradas = (_linha("CDB 0000", "99,00"), *muitas[1:])

        grande = mede(muitas, erradas, CAMPOS, iguais)
        pequeno = mede((TRES[0],), (TRES[0],), CAMPOS, iguais)

        total = agrega([grande, pequeno])

        assert total.acuracia("valor") == 40 / 41
        media_ingenua = (grande.acuracia("valor") + pequeno.acuracia("valor")) / 2
        assert total.acuracia("valor") != media_ingenua

    def test_agrega_junta_os_alinhamentos(self) -> None:
        um = mede(TRES, TRES[:2], CAMPOS, iguais)
        outro = mede((TRES[0],), (*TRES[:1], _linha("LCI 9", "1,00")), CAMPOS, iguais)

        total = agrega([um, outro])

        assert total.alinhamento.esperadas == 4
        assert len(total.alinhamento.faltantes) == 1
        assert len(total.alinhamento.inventadas) == 1

    def test_agregar_nada_nao_quebra(self) -> None:
        total = agrega([])

        assert total.recall == 1.0
        assert total.precisao == 1.0
