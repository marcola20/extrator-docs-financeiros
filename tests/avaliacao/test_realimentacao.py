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


def _informe(
    tmp_path: Path, ano: int, *, cpf: str = "15974832655", cnpj: str = "01829356000103"
) -> realimentacao.CasoDeRealimentacao:
    """Um caso de informe com identidade e ano controlados."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    pdf = tmp_path / f"informe-{ano}.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    return realimentacao.monta(
        arquivo_pdf=pdf,
        tipo="informe",
        hash_sha256=f"{ano}" * 16,
        payload={
            "layout": "instituicao_financeira",
            "ano_calendario": str(ano),
            "beneficiario_cpf": cpf,
            "fonte_pagadora_cnpj": cnpj,
        },
        correcoes={},
        revisor="revisor@exemplo",
    )


class TestPareamentoDeInforme:
    """O eval de informe processa pares; um caso sozinho mediria a falta do par."""

    def test_anos_consecutivos_do_mesmo_titular_formam_par(self, tmp_path: Path) -> None:
        pares = realimentacao.pareia([_informe(tmp_path, 2025), _informe(tmp_path, 2024)])

        assert len(pares) == 1
        anterior, atual = pares[0]
        assert anterior.campos["ano_calendario"] == "2024"
        assert atual.campos["ano_calendario"] == "2025"

    def test_a_ordem_sai_do_ano_e_nao_da_ordem_de_entrada(self, tmp_path: Path) -> None:
        """`cruza` compara o saldo anterior de N com o saldo de N-1; a ordem importa."""
        pares = realimentacao.pareia([_informe(tmp_path, 2024), _informe(tmp_path, 2025)])

        assert pares[0][0].campos["ano_calendario"] == "2024"

    def test_anos_nao_consecutivos_nao_formam_par(self, tmp_path: Path) -> None:
        """É o mesmo `ANOS_NAO_CONSECUTIVOS` que o cruzamento recusa."""
        assert realimentacao.pareia([_informe(tmp_path, 2022), _informe(tmp_path, 2025)]) == []

    def test_titular_diferente_nao_forma_par(self, tmp_path: Path) -> None:
        casos = [
            _informe(tmp_path, 2024),
            _informe(tmp_path / "outro", 2025, cpf="11144477735"),
        ]

        assert realimentacao.pareia(casos) == []

    def test_fonte_diferente_nao_forma_par(self, tmp_path: Path) -> None:
        outro = _informe(tmp_path / "outro", 2025, cnpj="11222333000181")

        assert realimentacao.pareia([_informe(tmp_path, 2024), outro]) == []

    def test_a_identidade_e_comparada_por_digitos(self, tmp_path: Path) -> None:
        """O transporte guarda o que estava impresso, e os dois formatos existem."""
        formatado = _informe(tmp_path / "f", 2025, cpf="159.748.326-55", cnpj="01.829.356/0001-03")

        assert len(realimentacao.pareia([_informe(tmp_path, 2024), formatado])) == 1

    def test_cada_documento_entra_em_no_maximo_um_par(self, tmp_path: Path) -> None:
        """Com 2023, 2024 e 2025 há dois pares possíveis que dividem o de 2024.

        Formar os dois mediria o mesmo documento duas vezes, e o relatório do
        eval é indexado por documento.
        """
        pares = realimentacao.pareia(
            [_informe(tmp_path, 2023), _informe(tmp_path, 2024), _informe(tmp_path, 2025)]
        )

        assert len(pares) == 1
        usados = [c.arquivo_pdf for par in pares for c in par]
        assert len(usados) == len(set(usados))

    def test_boleto_nao_e_pareado(self, tmp_path: Path) -> None:
        assert realimentacao.pareia([_caso(tmp_path), _caso(tmp_path)]) == []

    def test_com_par_faz_os_dois_apontarem_um_para_o_outro(self, tmp_path: Path) -> None:
        anterior, atual = realimentacao.pareia(
            [_informe(tmp_path, 2024), _informe(tmp_path, 2025)]
        )[0]

        a, b = realimentacao.com_par(anterior, atual)

        assert a.arquivo_do_par == b.arquivo_pdf
        assert b.arquivo_do_par == a.arquivo_pdf
        assert a.utilizavel and b.utilizavel

    def test_sem_par_o_informe_nao_e_utilizavel(self, tmp_path: Path) -> None:
        assert not _informe(tmp_path, 2024).utilizavel


class TestParesNoEvalDeInforme:
    def test_o_par_vira_corpus_do_eval(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.avaliacao import informe as eval_informe

        deposito = tmp_path / "realimentacao"
        for caso in realimentacao.com_par(
            *realimentacao.pareia([_informe(tmp_path, 2024), _informe(tmp_path, 2025)])[0]
        ):
            realimentacao.grava(caso, deposito)
        monkeypatch.setattr(realimentacao, "DIRETORIO_PADRAO", deposito)

        pares = eval_informe.pares_de_realimentacao()

        assert len(pares) == 1
        assert pares[0].anterior.gabarito["campos"]["ano_calendario"] == "2024"
        assert pares[0].atual.gabarito["campos"]["ano_calendario"] == "2025"
        assert pares[0].anterior.layout == "instituicao_financeira"

    def test_a_procedencia_separa_o_que_veio_de_correcao(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sem isto, duas passadas com corpora diferentes se somariam em silêncio."""
        from app.avaliacao import informe as eval_informe

        deposito = tmp_path / "realimentacao"
        for caso in realimentacao.com_par(
            *realimentacao.pareia([_informe(tmp_path, 2024), _informe(tmp_path, 2025)])[0]
        ):
            realimentacao.grava(caso, deposito)
        monkeypatch.setattr(realimentacao, "DIRETORIO_PADRAO", deposito)

        pares = eval_informe.carrega_pares(limpos=True, adversariais=False, limite=1)
        pares += eval_informe.pares_de_realimentacao()

        procedencia = eval_informe.procedencia(pares)

        assert procedencia["realimentacao"]["pares"] == 1
        assert procedencia["realimentacao"]["documentos"] == 2
        assert procedencia["limpo"]["semente"] is not None

    def test_sem_diretorio_nao_ha_par_e_nao_ha_erro(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.avaliacao import informe as eval_informe

        monkeypatch.setattr(realimentacao, "DIRETORIO_PADRAO", tmp_path / "vazio")

        assert eval_informe.pares_de_realimentacao() == []
