"""O comando que povoa a fila para demonstrar a tela, sem gastar cota."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.geradores import semeia_fila
from app.persistencia.modelos import Base, Decisao, Documento, Extracao, Rota, Sinal

BOLETO = Path("dados/sinteticos/boletos/boleto-001.pdf")


@pytest.fixture
def sessao(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'fila.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)()


@pytest.fixture
def abre_sessao(tmp_path: Path) -> semeia_fila.AbreSessao:
    """Uma sessão sobre SQLite, injetada em `semeia`.

    Exigir Postgres de pé para testar este comando contradiria a decisão da
    Fase 4.1 de a persistência ser opcional.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'fila.db'}", future=True)
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    @contextmanager
    def abre() -> Iterator[Session]:
        with fabrica() as aberta:
            yield aberta
            aberta.commit()

    return abre


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """`database_url` aponta para o mesmo SQLite das outras fixtures.

    `limpa` abre a conexão pela configuração, e não pela sessão injetada — ela
    apaga tabelas, e apagar precisa saber exatamente qual banco. Com a URL
    apontando para outro lugar, o teste passaria a limpar o Postgres de
    desenvolvimento de quem o tivesse de pé.
    """
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'fila.db'}",
        gemini_api_key=SecretStr("nao-usada"),
        llm_arquivo_cotas=tmp_path / "cotas.json",
        llm_cache_diretorio=tmp_path / "cache",
        auto_consistencia="condicional",
        persistencia_ativa=True,
    )


class TestNaoGastaCota:
    """A propriedade que faz este comando existir."""

    def test_o_provedor_nao_fala_com_a_api(self) -> None:
        """Ele lê o gabarito ao lado do PDF; não há SDK nem chave envolvidos."""
        provedor = semeia_fila.ProvedorDeGabarito([semeia_fila._conhecido_de_boleto(BOLETO, {})])

        assert provedor.nome == "gabarito"
        assert "sem-rede" in provedor.modelo

    def test_devolve_o_que_o_gabarito_diz(self) -> None:
        from app.extracao.schema_transporte import BoletoExtraido

        conhecido = semeia_fila._conhecido_de_boleto(BOLETO, {})
        provedor = semeia_fila.ProvedorDeGabarito([conhecido])
        texto = BOLETO.with_suffix(".json").read_text(encoding="utf-8")

        resultado = provedor.extrai(texto, BoletoExtraido)

        esperado = semeia_fila.gabarito_de(BOLETO)
        assert resultado.dados.valor == str(esperado["valor"])

    def test_o_cenario_pode_encenar_uma_leitura_errada(self) -> None:
        """É assim que a fila ganha um documento com sinal reprovado."""
        from app.extracao.schema_transporte import BoletoExtraido

        conhecido = semeia_fila._conhecido_de_boleto(BOLETO, {"valor": "99.999,99"})
        provedor = semeia_fila.ProvedorDeGabarito([conhecido])

        lido = provedor.extrai(
            BOLETO.with_suffix(".json").read_text(encoding="utf-8"), BoletoExtraido
        )

        assert lido.dados.valor == "99.999,99"

    def test_o_modulo_nao_importa_provedor_de_verdade(self) -> None:
        """Um import de `cria_provedor` aqui abriria a porta para gastar cota."""
        fonte = Path("app/geradores/semeia_fila.py").read_text(encoding="utf-8")

        assert "cria_provedor" not in fonte
        assert "google" not in fonte and "anthropic" not in fonte


class TestReconhecimentoDoDocumento:
    def test_separa_os_dois_informes_de_um_par(self) -> None:
        """Eles têm o mesmo CPF, e o ano de um aparece impresso no outro.

        O exercício só aparece no cabeçalho, e é ele que os separa — sem isso o
        provedor devolveria o gabarito errado e o cruzamento entre anos mediria
        outra coisa.
        """
        anterior = semeia_fila._conhecido_de_informe(
            Path("dados/sinteticos/informes/informe-001.pdf")
        )
        atual = semeia_fila._conhecido_de_informe(Path("dados/sinteticos/informes/informe-002.pdf"))

        assert anterior.digitos_marcadores == atual.digitos_marcadores, "mesmo titular"
        assert set(anterior.marcadores_de_texto).isdisjoint(atual.marcadores_de_texto)

    def test_o_marcador_cobre_as_duas_grafias_de_exercicio(self) -> None:
        """O comprovante imprime "Exercício **de** 2025"; o bancário, sem o "de".

        Uma forma só reconheceria metade do corpus, e o provedor devolveria o
        gabarito do outro documento do par — o cruzamento entre anos passaria a
        medir outra coisa.
        """
        from app.ingestao.leitor import ingere

        for nome in ("informe-001", "informe-003"):
            pdf = Path(f"dados/sinteticos/informes/{nome}.pdf")
            conhecido = semeia_fila._conhecido_de_informe(pdf)
            comparavel = semeia_fila._comparavel(ingere(pdf, com_ocr=False).texto)

            assert any(marca in comparavel for marca in conhecido.marcadores_de_texto), nome

    def test_texto_desconhecido_falha_alto(self) -> None:
        """Corpus regerado depois deste comando não pode virar gabarito errado."""
        from app.extracao.schema_transporte import BoletoExtraido

        provedor = semeia_fila.ProvedorDeGabarito([semeia_fila._conhecido_de_boleto(BOLETO, {})])

        with pytest.raises(AssertionError, match="corpus foi regerado"):
            provedor.extrai("um texto que não é documento nenhum", BoletoExtraido)


class TestCenariosPadrao:
    def test_cobrem_reprovacao_falta_de_cobertura_e_aprovacao(self) -> None:
        """Uma fila de documentos parecidos não demonstra o que a tela tem a dizer."""
        boletos, informes = semeia_fila.cenarios_padrao()

        assert any(c.sobrescreve for c in boletos), "algum caso com leitura errada"
        assert any(not c.sobrescreve for c in boletos), "algum caso com leitura fiel"
        assert len(informes) == 3, (
            "um par sem cobertura, um com cobertura, e um com o saldo trocado"
        )

    def test_incluem_o_par_de_comprovantes(self) -> None:
        """O caso do ADR 009: lido certo, e ainda assim ninguém conferiu."""
        _, informes = semeia_fila.cenarios_padrao()
        layouts = {
            json.loads(c.atual.with_suffix(".json").read_text(encoding="utf-8"))["layout"]
            for c in informes
        }

        assert layouts == {"fonte_pagadora", "instituicao_financeira"}

    def test_incluem_o_valor_divergente(self) -> None:
        """A tese do projeto num documento só, e o caso pedido para o GIF.

        A página não tem defeito que um detector veja: nenhum texto escondido,
        nenhuma instrução injetada. Ela imprime um valor e a linha digitável
        codifica outro, e o que barra é a aritmética.
        """
        boletos, _ = semeia_fila.cenarios_padrao()
        familias = {
            json.loads(c.pdf.with_suffix(".json").read_text(encoding="utf-8"))["ataque"]["nome"]
            for c in boletos
            if "adversariais" in str(c.pdf)
        }

        assert "valor_divergente" in familias

    def test_o_valor_divergente_nao_precisa_de_sobrescrita(self) -> None:
        """O gabarito já guarda o valor **impresso**, que é o falso (ADR 006).

        Encenar o erro com `sobrescreve` aqui seria enganoso: daria a entender
        que o modelo precisa errar para o ataque existir, quando o ponto é o
        oposto — ele lê a página certo, e mesmo assim não passa.
        """
        boletos, _ = semeia_fila.cenarios_padrao()
        divergente = next(c for c in boletos if "divergente" in c.rotulo)

        assert divergente.sobrescreve == {}

    def test_incluem_o_par_com_o_saldo_do_ano_anterior_trocado(self) -> None:
        """O único ataque que um adversário com controle da página não satisfaz.

        Nada dentro do documento o denuncia — DVs corretos, somas fechando, nada
        escondido. Quem o desmente é o informe do ano anterior, e é por isso que
        ele entra na demonstração: sem ele, o cruzamento entre anos aparece só
        como um sinal que sempre aprova.
        """
        _, informes = semeia_fila.cenarios_padrao()
        ataques = {
            json.loads(c.atual.with_suffix(".json").read_text(encoding="utf-8"))
            .get("ataque", {})
            .get("nome")
            for c in informes
        }

        assert "saldo_anterior_adulterado" in ataques

    def test_todos_os_pdfs_existem(self) -> None:
        boletos, informes = semeia_fila.cenarios_padrao()

        for cenario in boletos:
            assert cenario.pdf.is_file(), cenario.pdf
        for par in informes:
            assert par.anterior.is_file() and par.atual.is_file()


class TestSemeadura:
    def test_grava_documento_extracao_sinais_e_decisao(
        self, settings: Settings, abre_sessao: semeia_fila.AbreSessao
    ) -> None:
        boletos, _ = semeia_fila.cenarios_padrao()

        gravadas = semeia_fila.semeia(
            settings, boletos=boletos[:1], informes=[], com_ocr=False, sessao=abre_sessao
        )

        assert len(gravadas) == 1
        decisao, rotulo = gravadas[0]
        assert decisao.id is not None
        assert "alucinado" in rotulo

    def test_o_par_de_informes_grava_os_dois(
        self, settings: Settings, abre_sessao: semeia_fila.AbreSessao
    ) -> None:
        _, informes = semeia_fila.cenarios_padrao()

        gravadas = semeia_fila.semeia(
            settings, boletos=[], informes=informes[:1], com_ocr=False, sessao=abre_sessao
        )

        assert len(gravadas) == 2

    def test_o_valor_encenado_chega_ao_banco(
        self, settings: Settings, abre_sessao: semeia_fila.AbreSessao, sessao: Session
    ) -> None:
        boletos, _ = semeia_fila.cenarios_padrao()

        semeia_fila.semeia(
            settings, boletos=boletos[:1], informes=[], com_ocr=False, sessao=abre_sessao
        )

        extracao = sessao.scalars(select(Extracao)).one()
        assert extracao.payload["valor"] == "99.999,99"
        assert extracao.provedor == "gabarito"

    def test_o_sinal_reprovado_e_gravado(
        self, settings: Settings, abre_sessao: semeia_fila.AbreSessao, sessao: Session
    ) -> None:
        """É o que a tela mostra em "por que este documento está na fila"."""
        boletos, _ = semeia_fila.cenarios_padrao()

        semeia_fila.semeia(
            settings, boletos=boletos[:1], informes=[], com_ocr=False, sessao=abre_sessao
        )

        divergentes = [
            s.nome for s in sessao.scalars(select(Sinal)) if s.estado.value == "divergente"
        ]
        assert "digito_verificador" in divergentes


class TestLimpar:
    def test_apaga_a_fila(
        self, settings: Settings, abre_sessao: semeia_fila.AbreSessao, sessao: Session
    ) -> None:
        boletos, _ = semeia_fila.cenarios_padrao()
        semeia_fila.semeia(
            settings, boletos=boletos[:1], informes=[], com_ocr=False, sessao=abre_sessao
        )
        assert sessao.scalars(select(Documento)).all()

        semeia_fila.limpa(settings)

        assert sessao.scalars(select(Documento)).all() == []
        assert sessao.scalars(select(Decisao)).all() == []


class TestCli:
    def test_recusa_sem_persistencia(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sem banco não há fila para povoar, e o erro diz qual variável ligar."""
        monkeypatch.setattr(semeia_fila, "get_settings", lambda: Settings(_env_file=None))

        assert semeia_fila.main([]) == 1
        assert "PERSISTENCIA_ATIVA" in capsys.readouterr().err

    def test_a_flag_de_limpar_e_explicita(self) -> None:
        """Apagar a fila leva as correções junto; não pode ser o padrão."""
        assert semeia_fila._analisa_argumentos([]).limpar is False
        assert semeia_fila._analisa_argumentos(["--limpar"]).limpar is True

    def test_ocr_ligado_por_padrao(self) -> None:
        """Sem OCR a sanitização barra tudo e a fila sai sem contraste."""
        assert semeia_fila._analisa_argumentos([]).sem_ocr is False

    def test_se_vazia_nao_faz_nada_com_a_fila_povoada(
        self,
        settings: Settings,
        abre_sessao: semeia_fila.AbreSessao,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """É o que torna a partida do contêiner segura de repetir.

        O plano gratuito reinicia o serviço a cada despertar, e um comando de
        partida que semeasse sempre duplicaria a fila visita após visita.
        """
        boletos, _ = semeia_fila.cenarios_padrao()
        semeia_fila.semeia(
            settings, boletos=boletos[:1], informes=[], com_ocr=False, sessao=abre_sessao
        )
        monkeypatch.setattr(semeia_fila, "get_settings", lambda: settings)

        assert semeia_fila.main(["--se-vazia"]) == 0
        assert "já tem decisões" in capsys.readouterr().out

    def test_se_vazia_com_limpar_e_recusado(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        settings: Settings,
    ) -> None:
        """As duas flags se contradizem; obedecer a uma calada seria pior."""
        monkeypatch.setattr(semeia_fila, "get_settings", lambda: settings)

        assert semeia_fila.main(["--limpar", "--se-vazia"]) == 2
        assert "contradizem" in capsys.readouterr().err

    def test_ha_decisoes_e_falso_na_fila_vazia(self, settings: Settings) -> None:
        from sqlalchemy import create_engine

        from app.persistencia.modelos import Base

        Base.metadata.create_all(create_engine(settings.database_url))

        assert semeia_fila.ha_decisoes(settings) is False


class TestRotaResultante:
    """Os cenários produzem as rotas que a tela precisa mostrar.

    Precisa de OCR: sem a comparação texto/imagem a política da Fase 1.2 barra
    todo documento, e nenhum chega a ser auto-aprovado.
    """

    @pytest.mark.slow
    @pytest.mark.skipif(
        __import__("shutil").which("tesseract") is None, reason="tesseract não instalado"
    )
    def test_a_leitura_fiel_e_auto_aprovada_e_a_errada_nao(
        self, settings: Settings, abre_sessao: semeia_fila.AbreSessao
    ) -> None:
        boletos, _ = semeia_fila.cenarios_padrao()
        alucinado = boletos[0]
        fiel = next(c for c in boletos if not c.sobrescreve)

        gravadas = semeia_fila.semeia(
            settings, boletos=[alucinado, fiel], informes=[], com_ocr=True, sessao=abre_sessao
        )
        rotas = {rotulo: decisao.rota for decisao, rotulo in gravadas}

        assert rotas[alucinado.rotulo] is Rota.REVISAO_HUMANA
        assert rotas[fiel.rotulo] is Rota.AUTO_APROVADO

    @pytest.mark.slow
    @pytest.mark.skipif(
        __import__("shutil").which("tesseract") is None, reason="tesseract não instalado"
    )
    def test_o_comprovante_fica_so_por_falta_de_cobertura(
        self, settings: Settings, abre_sessao: semeia_fila.AbreSessao, sessao: Session
    ) -> None:
        """O caso mais importante da demonstração: lido certo, e não conferido."""
        _, informes = semeia_fila.cenarios_padrao()
        comprovante = next(c for c in informes if "comprovante" in c.rotulo)

        gravadas = semeia_fila.semeia(
            settings, boletos=[], informes=[comprovante], com_ocr=True, sessao=abre_sessao
        )

        for decisao, _ in gravadas:
            assert decisao.rota is Rota.REVISAO_HUMANA
        sem_cobertura = [
            s.nome for s in sessao.scalars(select(Sinal)) if s.estado.value == "sem_cobertura"
        ]
        assert "aritmetica" in sem_cobertura
        assert "cruzamento" in sem_cobertura
