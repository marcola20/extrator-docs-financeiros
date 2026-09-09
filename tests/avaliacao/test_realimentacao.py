"""Correção humana virando caso de eval, sem levar documento real para o git."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import eval as modulo_eval
from app.avaliacao import realimentacao
from app.avaliacao.exporta_realimentacao import casos_revisados
from app.persistencia.modelos import Rota

BOLETO = Path("dados/sinteticos/boletos/boleto-001.pdf")


def _caso(tmp_path: Path, **mudancas: object) -> realimentacao.CasoDeRealimentacao:
    valores: dict[str, object] = {
        "arquivo_pdf": BOLETO,
        "tipo": "boleto",
        "hash_sha256": "a" * 64,
        "payload": {"valor": "99.999,99", "beneficiario_nome": "Comércio Ltda"},
        "correcoes": {"valor": "1.847,30"},
        "decisao_id": 7,
        "revisor": "revisor@exemplo",
    }
    valores.update(mudancas)
    return realimentacao.monta(**valores)  # type: ignore[arg-type]


class TestDocumentoRealNaoEntraNoGit:
    """A regra do projeto não tem exceção; este módulo é desenhado em volta dela."""

    def test_o_diretorio_padrao_e_ignorado_pelo_git(self) -> None:
        ignorado = Path(".gitignore").read_text(encoding="utf-8")

        assert "dados/*" in ignorado
        assert str(realimentacao.DIRETORIO_PADRAO).startswith("dados/")

    def test_o_caso_guarda_caminho_e_hash_e_nao_o_conteudo(self, tmp_path: Path) -> None:
        caminho = realimentacao.grava(_caso(tmp_path), tmp_path)
        bruto = json.loads(caminho.read_text(encoding="utf-8"))

        assert bruto["arquivo_pdf"] == str(BOLETO)
        assert bruto["realimentacao"]["hash_sha256"] == "a" * 64
        assert len(caminho.read_bytes()) < 4000, "o caso não é uma cópia do PDF"

    def test_diretorio_ausente_devolve_vazio_em_vez_de_falhar(self, tmp_path: Path) -> None:
        """É o caso de um clone novo e do CI: o diretório nunca é versionado."""
        assert realimentacao.carrega(tmp_path / "nao-existe") == []


class TestProcedencia:
    def test_marca_a_origem_a_data_e_o_documento(self, tmp_path: Path) -> None:
        caso = _caso(tmp_path)

        assert caso.procedencia.origem == "correcao_humana"
        assert caso.procedencia.documento_de_origem == BOLETO.name
        assert caso.procedencia.exportado_em
        assert caso.procedencia.decisao_id == 7
        assert caso.procedencia.revisor == "revisor@exemplo"

    def test_registra_quais_campos_o_revisor_tocou(self, tmp_path: Path) -> None:
        caso = _caso(tmp_path, correcoes={"valor": "1,00", "vencimento": "01/01/2027"})

        assert caso.procedencia.campos_corrigidos == ("valor", "vencimento")

    def test_sobrevive_ao_json(self, tmp_path: Path) -> None:
        caso = _caso(tmp_path)

        de_volta = realimentacao.CasoDeRealimentacao.de_json(
            json.loads(json.dumps(caso.como_json()))
        )

        assert de_volta == caso


class TestGabaritoResultante:
    def test_a_correcao_sobrescreve_o_que_o_modelo_leu(self, tmp_path: Path) -> None:
        caso = _caso(tmp_path)

        assert caso.campos["valor"] == "1.847,30"

    def test_campo_nao_corrigido_e_confirmacao_e_nao_omissao(self, tmp_path: Path) -> None:
        """O revisor olhou a tela inteira antes de fechar; não corrigir é confirmar."""
        caso = _caso(tmp_path)

        assert caso.campos["beneficiario_nome"] == "Comércio Ltda"


class TestUtilizavel:
    def test_caso_cujo_pdf_sumiu_nao_e_utilizavel(self, tmp_path: Path) -> None:
        """Documento real vive fora do repositório e pode ter sido apagado."""
        caso = _caso(tmp_path, arquivo_pdf=tmp_path / "sumiu.pdf")

        assert not caso.utilizavel

    def test_informe_sem_par_nao_e_utilizavel(self, tmp_path: Path) -> None:
        """Sem o par, o cruzamento entre anos não teria o que conferir."""
        caso = _caso(tmp_path, tipo="informe")

        assert caso.arquivo_do_par is None
        assert not caso.utilizavel

    def test_o_inventario_conta_os_que_nao_dao_para_medir(self, tmp_path: Path) -> None:
        casos = [_caso(tmp_path), _caso(tmp_path, arquivo_pdf=tmp_path / "sumiu.pdf")]

        inventario = realimentacao.inventaria(casos)

        assert inventario.casos == 2
        assert inventario.utilizaveis == 1
        assert inventario.sem_arquivo == 1


class TestReexportar:
    def test_o_mesmo_documento_atualiza_em_vez_de_duplicar(self, tmp_path: Path) -> None:
        realimentacao.grava(_caso(tmp_path, correcoes={"valor": "1,00"}), tmp_path)
        realimentacao.grava(_caso(tmp_path, correcoes={"valor": "2,00"}), tmp_path)

        casos = realimentacao.carrega(tmp_path)

        assert len(casos) == 1
        assert casos[0].campos["valor"] == "2,00"


class TestFlagDoEval:
    def test_desligada_por_padrao(self) -> None:
        """Misturar sem distinção contaminaria a comparação com os baselines."""
        assert not modulo_eval._analisa_argumentos([]).com_realimentacao
        assert modulo_eval._analisa_argumentos(["--com-realimentacao"]).com_realimentacao

    def test_sem_a_flag_o_corpus_e_so_o_sintetico(self) -> None:
        argumentos = modulo_eval._analisa_argumentos([])

        casos = modulo_eval._corpus_completo(argumentos)

        assert all("realimentacao" not in c.gabarito for c in casos)

    def test_a_procedencia_registra_a_realimentacao(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sem isto, duas passadas com corpora diferentes se somariam em silêncio."""
        realimentacao.grava(_caso(tmp_path), tmp_path)
        monkeypatch.setattr(realimentacao, "DIRETORIO_PADRAO", tmp_path)

        casos = modulo_eval.carrega_casos(limpos=True, adversariais=False, limite=2)
        casos += modulo_eval.casos_de_realimentacao()

        procedencia = modulo_eval._procedencia(casos)

        assert procedencia["realimentacao"]["casos"] == 1
        assert procedencia["realimentacao"]["revisores"] == ["revisor@exemplo"]

    def test_a_retomada_recusa_somar_passada_com_e_sem_realimentacao(self, tmp_path: Path) -> None:
        """`corpus` inteiro entra na conferência de compatibilidade."""
        from app.avaliacao.relatorio import RetomadaInvalida, confere_compatibilidade

        anterior = {"corpus": {"limpo": {"semente": 2026}}}

        with pytest.raises(RetomadaInvalida, match="corpus"):
            confere_compatibilidade(
                anterior,
                tmp_path / "r.json",
                esperado=(("corpus", {"limpo": {"semente": 2026}, "realimentacao": {"casos": 1}}),),
            )


class TestExportacaoDoBanco:
    def test_exporta_so_o_que_foi_fechado(self, cliente: TestClient, sessao: Session) -> None:
        """Gabarito pela metade entraria na medição afirmando o que ninguém conferiu."""
        from tests.api.test_revisao import _monta

        aberta = _monta(sessao, arquivo="aberta.pdf")
        fechada = _monta(sessao, arquivo="fechada.pdf")
        cliente.post(
            f"/revisao/{fechada.id}/correcoes",
            json={"correcoes": [{"campo": "valor", "valor_corrigido": "1.847,30"}]},
        )

        casos = casos_revisados(sessao)

        assert [c.procedencia.decisao_id for c in casos] == [fechada.id]
        assert aberta.revisada_em is None

    def test_o_caso_exportado_leva_a_correcao_e_o_resto_do_payload(
        self, cliente: TestClient, sessao: Session
    ) -> None:
        from tests.api.test_revisao import _monta

        decisao = _monta(sessao)
        cliente.post(
            f"/revisao/{decisao.id}/correcoes",
            json={
                "correcoes": [{"campo": "valor", "valor_corrigido": "1.847,30"}],
                "revisor": "revisor@exemplo",
            },
        )

        caso = casos_revisados(sessao)[0]

        assert caso.campos["valor"] == "1.847,30"
        assert caso.campos["beneficiario_nome"] == "Comércio Ltda"
        assert caso.procedencia.revisor == "revisor@exemplo"
        assert caso.procedencia.campos_corrigidos == ("valor",)

    def test_documento_sem_extracao_nao_vira_caso(
        self, cliente: TestClient, sessao: Session
    ) -> None:
        """Sem leitura não há o que comparar com a correção."""
        from tests.api.test_revisao import _monta

        decisao = _monta(sessao, com_extracao=False, arquivo="sem-texto.pdf")
        cliente.post(
            f"/revisao/{decisao.id}/correcoes",
            json={"correcoes": [{"campo": "valor", "valor_corrigido": "1,00"}]},
        )

        assert casos_revisados(sessao) == []

    def test_auto_aprovado_nao_revisado_nao_vira_caso(self, sessao: Session) -> None:
        from tests.api.test_revisao import _monta

        _monta(sessao, rota=Rota.AUTO_APROVADO, arquivo="auto.pdf")

        assert casos_revisados(sessao) == []
