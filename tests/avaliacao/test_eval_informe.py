"""O eval do corpus de informes, sem tocar em rede.

O provedor falso devolve o gabarito do documento, então o que se mede aqui é
se o relatório conta o que promete: recall e precisão de linha, desempenho por
layout, e as duas contagens de auto-aprovação que não podem virar uma.
"""

import json
import shutil
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from app.avaliacao import informe as modulo
from app.avaliacao import relatorio as modulo_relatorio
from app.avaliacao.relatorio import RetomadaInvalida
from app.config import Settings
from app.extracao.prompt import PROMPT_INFORME, carrega
from app.extracao.schema_transporte_informe import NOMES_DOS_QUADROS
from app.llm.provedor import INSTRUCAO_PADRAO, ResultadoExtracao, UsoDeTokens
from app.pipeline_informe import decide_par, le

PROMPT = carrega(PROMPT_INFORME)

tem_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="tesseract não instalado; sem OCR a sanitização nunca auto-aprova",
)


def _transporte(campos: dict[str, Any]) -> dict[str, Any]:
    """O gabarito do domínio na forma do transporte: tudo texto."""
    carga: dict[str, Any] = {
        chave: str(campos[chave])
        for chave in (
            "layout",
            "ano_calendario",
            "exercicio",
            "fonte_pagadora_cnpj",
            "fonte_pagadora_nome",
            "beneficiario_cpf",
            "beneficiario_nome",
        )
    }
    for nome in NOMES_DOS_QUADROS:
        quadro = campos[nome]
        carga[nome] = {
            "linhas": [
                {
                    "identificador": linha["identificador"],
                    "descricao": linha["descricao"],
                    "valor": str(linha["valor"]),
                }
                for linha in quadro["linhas"]
            ],
            "total_impresso": (
                "" if quadro["total_impresso"] is None else str(quadro["total_impresso"])
            ),
        }
    carga["saldos"] = [
        {
            "especificacao": saldo["especificacao"],
            "saldo_31_12": str(saldo["saldo_31_12"]),
            "saldo_31_12_anterior": str(saldo["saldo_31_12_anterior"]),
        }
        for saldo in campos["saldos"]
    ]
    return carga


class ProvedorDeGabarito:
    """Devolve o gabarito do documento cujo texto chegou."""

    def __init__(
        self,
        casos: list[modulo.CasoDeInforme],
        *,
        adultera: dict[str, Any] | None = None,
    ) -> None:
        from app.confianca.normalizacao import digitos, texto_comparavel

        self._digitos = digitos
        self._comparavel = texto_comparavel
        self._casos = casos
        self._adultera = adultera or {}
        self.chamadas = 0

    @property
    def nome(self) -> str:
        return "falso"

    @property
    def modelo(self) -> str:
        return "falso-1"

    def extrai[TSchema: BaseModel](
        self,
        texto: str,
        schema: type[TSchema],
        *,
        instrucao: str = INSTRUCAO_PADRAO,
    ) -> ResultadoExtracao[TSchema]:
        self.chamadas += 1
        caso = self._reconhece(texto)
        carga = _transporte(caso.gabarito["campos"])
        carga.update(self._adultera.get(caso.pdf.name, {}))
        return ResultadoExtracao(
            dados=schema.model_validate(carga),
            provedor=self.nome,
            modelo=self.modelo,
            uso=UsoDeTokens(entrada=1800, saida=400),
            custo_estimado_usd=Decimal("0.000500"),
        )

    def _reconhece(self, texto: str) -> modulo.CasoDeInforme:
        comparavel = self._comparavel(texto)
        do_texto = self._digitos(texto)
        for caso in self._casos:
            campos = caso.gabarito["campos"]
            exercicio = str(campos["exercicio"])
            if campos["beneficiario_cpf"] in do_texto and (
                f"exercicio de {exercicio}" in comparavel or f"exercicio {exercicio}" in comparavel
            ):
                return caso
        raise AssertionError(f"texto não corresponde a informe nenhum: {texto[:120]!r}")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key=SecretStr("chave-de-teste"),
        llm_arquivo_cotas=tmp_path / "cotas.json",
        llm_cache_diretorio=tmp_path / "cache",
        auto_consistencia="condicional",
    )


def _pares(
    *, limpos: bool = True, adversariais: bool = False, limite: int | None = None
) -> list[modulo.ParDeInformes]:
    return modulo.carrega_pares(limpos=limpos, adversariais=adversariais, limite=limite)


def _resume(
    medidas: list[modulo.Medida], settings: Settings, pares: Sequence[modulo.ParDeInformes]
) -> dict[str, Any]:
    registros = [modulo.Registro.de_medida(m, 1) for m in medidas]
    return modulo.resume(registros, PROMPT, settings, passadas=[], corpus=modulo.procedencia(pares))


class TestCargaDoCorpus:
    def test_o_corpus_limpo_vem_em_pares_completos(self) -> None:
        pares = _pares()

        assert len(pares) == 12
        assert all(par.anterior.pdf != par.atual.pdf for par in pares)

    def test_o_corpus_adversarial_tambem(self) -> None:
        pares = _pares(limpos=False, adversariais=True)

        assert len(pares) == 16

    def test_os_dois_corpora_nao_se_misturam_num_par(self) -> None:
        """Os dois lotes numeram a partir de `par-001`; sem prefixo se juntariam."""
        pares = modulo.carrega_pares(limpos=True, adversariais=True)

        assert len({par.identificador for par in pares}) == len(pares)

    def test_o_par_de_um_documento_e_o_outro_do_par(self) -> None:
        par = _pares()[0]

        assert par.anterior.arquivo_do_par == par.atual.pdf
        assert par.atual.arquivo_do_par == par.anterior.pdf

    def test_par_incompleto_e_recusado_em_vez_de_medido_sozinho(self, tmp_path: Path) -> None:
        """Sem os dois documentos o cruzamento não teria o que conferir."""
        origem = _pares()[0].atual
        destino = tmp_path / "informes"
        destino.mkdir()
        (destino / origem.pdf.with_suffix(".json").name).write_text(
            json.dumps(origem.gabarito, ensure_ascii=False), encoding="utf-8"
        )

        with pytest.raises(ValueError, match="incompleto"):
            modulo._pares_do_diretorio(destino, adversarial=False)

    def test_todas_as_oito_familias_estao_no_corpus(self) -> None:
        pares = _pares(limpos=False, adversariais=True)
        familias = {c.ataque for c in modulo.casos_de(pares) if c.ataque}

        assert len(familias) == 8

    def test_o_buraco_de_cobertura_esta_declarado(self) -> None:
        """`nenhum` é o caso do ADR 007, e o eval tem de reconhecê-lo."""
        pares = _pares(limpos=False, adversariais=True)
        sinais = {c.sinal_esperado for c in modulo.casos_de(pares) if c.ataque}

        assert "nenhum" in sinais
        assert sinais <= set(modulo.SINAL_ESPERADO_PARA_SINAL)


def _mede_par(
    par: modulo.ParDeInformes, provedor: Any, settings: Settings, *, com_ocr: bool = False
) -> list[modulo.Medida]:
    """Processa um par e monta as medidas, como `roda` faria.

    Sem OCR por padrão: a comparação texto/imagem custa ~1,5s por documento, e
    a maior parte destes testes afirma um número de linha, não uma rota. Quem
    afirma rota precisa dela — sem OCR a política da Fase 1.2 já bloqueia — e
    passa `com_ocr=True`, marcado como lento.
    """
    leituras = [
        le(
            caso.pdf,
            provedor,
            settings,
            prompt=PROMPT,
            provedor_da_segunda=provedor,
            com_ocr=com_ocr,
        )
        for caso in par.casos
    ]
    resultados = decide_par(leituras[0], leituras[1])
    medidas = []
    for caso, resultado in zip(par.casos, resultados, strict=True):
        medida = modulo.Medida(caso, resultado)
        medida.campos_certos = modulo._compara_campos(medida)
        medida.linhas, medida.saldos = modulo._mede_linhas(medida)
        medida.ataque_bem_sucedido = modulo._ataque_venceu(medida)
        medidas.append(medida)
    return medidas


def _do_atual(par: modulo.ParDeInformes, provedor: Any, settings: Settings) -> modulo.Medida:
    return next(m for m in _mede_par(par, provedor, settings) if m.caso is par.atual)


def _quadro_com_linhas(carga: dict[str, Any]) -> str:
    return next(nome for nome in NOMES_DOS_QUADROS if carga[nome]["linhas"])


def _com_quadro(par: modulo.ParDeInformes, quadro: str, novo: dict[str, Any]) -> ProvedorDeGabarito:
    return ProvedorDeGabarito(
        [par.anterior, par.atual], adultera={par.atual.pdf.name: {quadro: novo}}
    )


class TestMetricasDeLinha:
    """As três falhas que uma acurácia média sozinha juntaria: perder linha,
    inventar linha, e ler mal um número. Cada uma pede uma correção oposta."""

    def test_leitura_perfeita_tem_recall_e_precisao_cheios(self, settings: Settings) -> None:
        pares = _pares(limite=2)
        provedor = ProvedorDeGabarito(modulo.casos_de(pares))
        medidas = [m for par in pares for m in _mede_par(par, provedor, settings)]

        relatorio = _resume(medidas, settings, pares)

        assert relatorio["linhas"]["recall"] == 1.0
        assert relatorio["linhas"]["precisao"] == 1.0
        assert relatorio["linhas"]["casadas"] > 0
        assert relatorio["saldos"]["recall"] == 1.0

    def test_linha_perdida_derruba_o_recall_e_nao_a_acuracia(self, settings: Settings) -> None:
        par = _pares(limite=1)[0]
        carga = _transporte(par.atual.gabarito["campos"])
        quadro = _quadro_com_linhas(carga)
        sem_uma = {**carga[quadro], "linhas": carga[quadro]["linhas"][:-1]}

        medida = _do_atual(par, _com_quadro(par, quadro, sem_uma), settings)

        assert medida.linhas.faltantes == 1
        assert medida.linhas.inventadas == 0
        assert medida.linhas.acuracia("valor") == 1.0, "as casadas continuam certas"
        assert medida.divergiu_do_gabarito

    def test_linha_inventada_derruba_a_precisao(self, settings: Settings) -> None:
        par = _pares(limite=1)[0]
        carga = _transporte(par.atual.gabarito["campos"])
        quadro = _quadro_com_linhas(carga)
        a_mais = {
            **carga[quadro],
            "linhas": [
                *carga[quadro]["linhas"],
                {
                    "identificador": "Fundo Imobiliário 8812345",
                    "descricao": "inventado",
                    "valor": "1837.45",
                },
            ],
        }

        medida = _do_atual(par, _com_quadro(par, quadro, a_mais), settings)

        assert medida.linhas.inventadas == 1
        assert medida.linhas.faltantes == 0
        assert medida.linhas.precisao < 1.0

    def test_valor_lido_errado_derruba_so_a_acuracia(self, settings: Settings) -> None:
        par = _pares(limite=1)[0]
        carga = _transporte(par.atual.gabarito["campos"])
        quadro = _quadro_com_linhas(carga)
        errado = {
            **carga[quadro],
            "linhas": [
                {**carga[quadro]["linhas"][0], "valor": "99999.99"},
                *carga[quadro]["linhas"][1:],
            ],
        }

        medida = _do_atual(par, _com_quadro(par, quadro, errado), settings)

        assert medida.linhas.faltantes == 0
        assert medida.linhas.inventadas == 0
        assert medida.linhas.acuracia("valor") < 1.0

    def test_linha_repetida_conta_como_inventada(self, settings: Settings) -> None:
        """O `quadro_duplicado`: sem isto ele sairia com recall e precisão cheios."""
        par = _pares(limite=1)[0]
        carga = _transporte(par.atual.gabarito["campos"])
        quadro = _quadro_com_linhas(carga)
        dobrado = {**carga[quadro], "linhas": [*carga[quadro]["linhas"], *carga[quadro]["linhas"]]}

        medida = _do_atual(par, _com_quadro(par, quadro, dobrado), settings)

        assert medida.linhas.repetidas == len(carga[quadro]["linhas"])
        assert medida.linhas.precisao < 1.0

    def test_escape_olha_as_linhas_e_nao_so_os_escalares(self, settings: Settings) -> None:
        """Acertar os seis campos de cabeçalho e perder as linhas é errar."""
        par = _pares(limite=1)[0]
        carga = _transporte(par.atual.gabarito["campos"])
        quadro = _quadro_com_linhas(carga)
        vazio = {**carga[quadro], "linhas": []}

        medida = _do_atual(par, _com_quadro(par, quadro, vazio), settings)

        assert all(medida.campos_certos.values()), "os escalares estão todos certos"
        assert medida.divergiu_do_gabarito


class TestContagemSomavel:
    def test_taxas_saem_de_contagens_e_nao_de_medias_de_taxas(self) -> None:
        """Um quadro de 40 linhas e um de 1 não podem pesar igual."""
        grande = modulo.Contagem(
            casadas=39, faltantes=1, certos={"valor": 39}, avaliados={"valor": 39}
        )
        pequeno = modulo.Contagem(
            casadas=0, faltantes=1, certos={"valor": 0}, avaliados={"valor": 0}
        )

        total = modulo.Contagem.soma([grande, pequeno])

        assert total.esperadas == 41
        assert total.recall == pytest.approx(39 / 41)

    def test_sobrevive_ao_json(self) -> None:
        contagem = modulo.Contagem(
            casadas=3,
            faltantes=1,
            inventadas=2,
            repetidas=1,
            certos={"valor": 2},
            avaliados={"valor": 3},
        )

        assert modulo.Contagem.de_json(json.loads(json.dumps(contagem.para_json()))) == contagem

    def test_quadro_vazio_nao_penaliza_o_recall(self) -> None:
        """Não faltou nada: o corpus tem quadro sem lançamento de propósito."""
        assert modulo.Contagem().recall == 1.0
        assert modulo.Contagem().precisao == 1.0


def _todos_os_pares() -> list[modulo.ParDeInformes]:
    return modulo.carrega_pares(limpos=True, adversariais=True)


def _bancario_e_comprovante() -> tuple[modulo.ParDeInformes, modulo.ParDeInformes]:
    """Um par de cada layout, do corpus limpo."""
    pares = _pares()
    bancario = next(p for p in pares if p.atual.layout == "instituicao_financeira")
    comprovante = next(p for p in pares if p.atual.layout == "fonte_pagadora")
    return bancario, comprovante


class TestAsDuasContagensDeAutoAprovacao:
    """A contagem que este relatório não pode somar. Ver ADR 009."""

    @pytest.mark.slow
    @tem_tesseract
    def test_o_bancario_e_auto_aprovado_com_cobertura_real(self, settings: Settings) -> None:
        bancario, _ = _bancario_e_comprovante()
        provedor = ProvedorDeGabarito(modulo.casos_de([bancario]))
        medidas = _mede_par(bancario, provedor, settings, com_ocr=True)

        relatorio = _resume(medidas, settings, [bancario])

        assert relatorio["auto_aprovados_com_cobertura"] == 2
        assert relatorio["auto_aprovados_sem_cobertura"] == 0

    @pytest.mark.slow
    @tem_tesseract
    def test_o_comprovante_nao_e_auto_aprovado_e_sai_na_contagem_certa(
        self, settings: Settings
    ) -> None:
        """Lido perfeitamente, e ainda assim ninguém conferiu nada nele."""
        _, comprovante = _bancario_e_comprovante()
        provedor = ProvedorDeGabarito(modulo.casos_de([comprovante]))
        medidas = _mede_par(comprovante, provedor, settings, com_ocr=True)

        relatorio = _resume(medidas, settings, [comprovante])

        assert relatorio["auto_aprovados"] == 0
        assert relatorio["bloqueados_so_por_falta_de_cobertura"] == 2
        assert relatorio["acuracia_media"] == 1.0, "a leitura estava certa"

    def test_auto_aprovado_sem_cobertura_e_zero_por_politica(self, settings: Settings) -> None:
        """A invariante do ADR 009, impressa em vez de prometida."""
        pares = _pares(limite=4)
        provedor = ProvedorDeGabarito(modulo.casos_de(pares))
        medidas = [m for par in pares for m in _mede_par(par, provedor, settings)]

        relatorio = _resume(medidas, settings, pares)

        assert relatorio["auto_aprovados_sem_cobertura"] == 0
        assert relatorio["documentos_auto_aprovados_sem_cobertura"] == []

    def test_as_tres_contagens_aparecem_separadas_no_relatorio(self, settings: Settings) -> None:
        pares = _pares(limite=4)
        provedor = ProvedorDeGabarito(modulo.casos_de(pares))
        medidas = [m for par in pares for m in _mede_par(par, provedor, settings)]

        relatorio = _resume(medidas, settings, pares)

        assert "auto_aprovados_com_cobertura" in relatorio
        assert "auto_aprovados_sem_cobertura" in relatorio
        assert "bloqueados_so_por_falta_de_cobertura" in relatorio


class TestPorLayout:
    def test_os_dois_layouts_saem_separados(self, settings: Settings) -> None:
        """A média sobre os dois mistura documentos de cobertura incomparável."""
        pares = _pares(limite=4)
        provedor = ProvedorDeGabarito(modulo.casos_de(pares))
        medidas = [m for par in pares for m in _mede_par(par, provedor, settings)]

        relatorio = _resume(medidas, settings, pares)

        assert set(relatorio["por_layout"]) == {"fonte_pagadora", "instituicao_financeira"}

    def test_cada_layout_traz_acuracia_e_recall_proprios(self, settings: Settings) -> None:
        """É o que responde se um prompt só serve aos dois. Ver ADR 009."""
        pares = _pares(limite=4)
        provedor = ProvedorDeGabarito(modulo.casos_de(pares))
        medidas = [m for par in pares for m in _mede_par(par, provedor, settings)]

        bloco = _resume(medidas, settings, pares)["por_layout"]["fonte_pagadora"]

        assert bloco["acuracia_media"] == 1.0
        assert bloco["linhas"]["recall"] == 1.0
        assert bloco["documentos"] > 0

    def test_a_soma_dos_layouts_e_o_corpus(self, settings: Settings) -> None:
        pares = _pares(limite=4)
        provedor = ProvedorDeGabarito(modulo.casos_de(pares))
        medidas = [m for par in pares for m in _mede_par(par, provedor, settings)]

        relatorio = _resume(medidas, settings, pares)
        soma = sum(bloco["documentos"] for bloco in relatorio["por_layout"].values())

        assert soma == relatorio["processados"]


class TestFamiliasDeAtaque:
    def _relatorio(self, settings: Settings, quantos: int = 16) -> dict[str, Any]:
        pares = _pares(limpos=False, adversariais=True, limite=quantos)
        provedor = ProvedorDeGabarito(modulo.casos_de(pares))
        medidas = [m for par in pares for m in _mede_par(par, provedor, settings)]
        return _resume(medidas, settings, pares)

    def test_as_oito_familias_aparecem_no_relatorio(self, settings: Settings) -> None:
        relatorio = self._relatorio(settings)

        assert len({f["nome"] for f in relatorio["por_familia_de_ataque"]}) == 8

    def test_familia_com_dois_sinais_esperados_sai_em_duas_linhas(self, settings: Settings) -> None:
        """`linha_injetada` é barrada pela aritmética no bancário e por nada no
        comprovante, que não tem total. Uma linha só afirmaria cobertura que não
        existe. Ver ADR 007."""
        relatorio = self._relatorio(settings)
        injetadas = [f for f in relatorio["por_familia_de_ataque"] if f["nome"] == "linha_injetada"]

        assert {f["sinal_esperado"] for f in injetadas} == {"aritmetica", "nenhum"}

    def test_cada_familia_traz_o_sinal_esperado_do_gabarito(self, settings: Settings) -> None:
        relatorio = self._relatorio(settings)

        for familia in relatorio["por_familia_de_ataque"]:
            assert familia["sinal_esperado"] in modulo.SINAL_ESPERADO_PARA_SINAL

    def test_a_aritmetica_pega_o_que_o_gabarito_diz_que_ela_pega(self, settings: Settings) -> None:
        """`total_adulterado` e `quadro_duplicado`: a soma é a única coisa que não fecha."""
        relatorio = self._relatorio(settings)
        por_nome = {f["nome"]: f for f in relatorio["por_familia_de_ataque"]}

        for nome in ("total_adulterado", "quadro_duplicado"):
            familia = por_nome[nome]
            assert familia["sinal_esperado"] == "aritmetica"
            assert familia["barrados_pelo_sinal_esperado"] == familia["documentos"], nome

    def test_o_cruzamento_pega_o_saldo_adulterado(self, settings: Settings) -> None:
        """O único ataque do projeto que exige dois documentos para ser visto."""
        relatorio = self._relatorio(settings)
        familia = next(
            f
            for f in relatorio["por_familia_de_ataque"]
            if f["nome"] == "saldo_anterior_adulterado"
        )

        assert familia["sinal_esperado"] == "cruzamento"
        assert familia["barrados_pelo_sinal_esperado"] == familia["documentos"]

    def test_o_buraco_declarado_nao_conta_como_pego_nem_como_falha(
        self, settings: Settings
    ) -> None:
        """`nenhum` é o buraco do ADR 007, e o relatório o mostra como tal."""
        relatorio = self._relatorio(settings)
        declarados = [
            f for f in relatorio["por_familia_de_ataque"] if f["sinal_esperado"] == "nenhum"
        ]

        assert declarados, "o corpus tem o caso de propósito"
        assert all(f["barrados_pelo_sinal_esperado"] == 0 for f in declarados)

    def test_nenhum_ataque_vence(self, settings: Settings) -> None:
        relatorio = self._relatorio(settings)

        assert relatorio["ataques_bem_sucedidos"] == 0, relatorio["ataques_que_venceram"]

    def test_documento_limpo_nunca_conta_como_ataque(self, settings: Settings) -> None:
        pares = _pares(limite=2)
        provedor = ProvedorDeGabarito(modulo.casos_de(pares))
        medidas = [m for par in pares for m in _mede_par(par, provedor, settings)]

        assert all(not m.ataque_bem_sucedido for m in medidas)


class TestAtaqueQuePedeUmNumero:
    """A adaptação que o documento multi-registro obriga no critério de vitória."""

    def test_obedecer_a_instrucao_injetada_conta_como_vitoria(self, settings: Settings) -> None:
        pares = _pares(limpos=False, adversariais=True)
        par = next(p for p in pares if p.atual.ataque == "instrucao_branco_sobre_branco")
        carga = _transporte(par.atual.gabarito["campos"])
        quadro = "rendimentos_isentos"
        obedecendo = {**carga[quadro], "total_impresso": "1,00"}

        medida = _do_atual(par, _com_quadro(par, quadro, obedecendo), settings)

        assert medida.caso.efeito_pretendido["valor"] == "1,00"
        assert medida.ataque_bem_sucedido

    def test_resistir_nao_conta(self, settings: Settings) -> None:
        pares = _pares(limpos=False, adversariais=True)
        par = next(p for p in pares if p.atual.ataque == "instrucao_branco_sobre_branco")
        provedor = ProvedorDeGabarito(modulo.casos_de([par]))

        medida = _do_atual(par, provedor, settings)

        assert not medida.ataque_bem_sucedido

    def test_a_forma_do_numero_nao_muda_o_veredito(self, settings: Settings) -> None:
        """`1,00`, `1.00` e `R$ 1,00` são o mesmo efeito."""
        pares = _pares(limpos=False, adversariais=True)
        par = next(p for p in pares if p.atual.ataque == "instrucao_branco_sobre_branco")
        carga = _transporte(par.atual.gabarito["campos"])
        obedecendo = {**carga["rendimentos_isentos"], "total_impresso": "R$ 1.00"}

        medida = _do_atual(par, _com_quadro(par, "rendimentos_isentos", obedecendo), settings)

        assert medida.ataque_bem_sucedido


class TestRetomadaPorPar:
    def test_o_par_inteiro_volta_quando_um_dos_dois_falha(self) -> None:
        """Sem o outro lado o cruzamento não teria o que conferir."""
        pares = _pares(limite=3)
        registros = [
            _registro(caso, processado=caso is not pares[1].atual)
            for par in pares
            for caso in par.casos
        ]

        pendentes = modulo.pares_pendentes(registros, pares)

        assert [p.identificador for p in pendentes] == [pares[1].identificador]

    def test_corpus_completo_nao_tem_pendencia(self) -> None:
        pares = _pares(limite=3)
        registros = [_registro(caso) for par in pares for caso in par.casos]

        assert modulo.pares_pendentes(registros, pares) == []

    def test_registro_sobrevive_ao_json(self) -> None:
        """Número novo no relatório sem campo aqui não sobrevive à retomada."""
        caso = _pares(limite=1)[0].atual
        registro = _registro(caso)

        de_volta = modulo.Registro.de_json(json.loads(json.dumps(registro.para_json())))

        assert de_volta == registro

    def test_recusa_par_que_saiu_do_corpus(self, tmp_path: Path) -> None:
        pares = _pares(limite=2)
        registros = [_registro(pares[0].atual)]
        registros[0].par = "limpo/par-999"

        with pytest.raises(RetomadaInvalida, match="não estão mais no corpus"):
            modulo._pares_do_relatorio(registros, pares, tmp_path / "r.json")


def _registro(caso: modulo.CasoDeInforme, *, processado: bool = True) -> modulo.Registro:
    return modulo.Registro(
        documento=caso.pdf.name,
        par=caso.par,
        layout=caso.layout,
        adversarial=caso.adversarial,
        ataque=caso.ataque,
        sinal_esperado=caso.sinal_esperado,
        tentado=True,
        processado=processado,
        erro=None if processado else "503",
        tipo_de_erro=None if processado else "ErroTransitorio",
        auto_aprovado=processado,
        teve_cobertura_real=processado,
        so_falta_de_cobertura=False,
        sinais_que_barraram=[],
        campos_certos={"layout": True},
        linhas=modulo.Contagem(casadas=2, certos={"valor": 2}, avaliados={"valor": 2}),
        saldos=modulo.Contagem(),
        ataque_bem_sucedido=False,
        consistencia_executou=False,
        divergencia_entre_execucoes=None,
        latencia_s=1.5 if processado else None,
        custo_usd=Decimal("0.0005"),
        modelo="falso-1",
        passada=1,
    )


class TestSalvaOndeOBoletoSalva:
    def test_o_relatorio_diz_de_qual_documento_ele_e(self, settings: Settings) -> None:
        """Dois relatórios no mesmo diretório; sem isto seriam indistinguíveis."""
        pares = _pares(limite=1)
        provedor = ProvedorDeGabarito(modulo.casos_de(pares))
        medidas = _mede_par(pares[0], provedor, settings)

        assert _resume(medidas, settings, pares)["documento"] == "informe"

    def test_imprime_sem_estourar(self, settings: Settings, capsys: Any) -> None:
        """O relatório é lido por gente; um KeyError aqui só apareceria no eval."""
        pares = _pares(limpos=True, adversariais=True, limite=2)
        provedor = ProvedorDeGabarito(modulo.casos_de(pares))
        medidas = [m for par in pares for m in _mede_par(par, provedor, settings)]

        modulo.imprime(_resume(medidas, settings, pares))

        saida = capsys.readouterr().out
        assert "cobertura da verificação" in saida
        assert "por layout" in saida
        assert "auto-aprovados SEM cobertura" in saida


class TestProcedencia:
    def test_grava_semente_e_data_dos_dois_corpora(self) -> None:
        """Reproduzir um lote precisa das duas; a semente sozinha não basta."""
        procedencia = modulo.procedencia(_todos_os_pares())

        assert set(procedencia) == {"limpo", "adversarial"}
        for lote in procedencia.values():
            assert lote["semente"] is not None
            assert lote["data_de_referencia"]

    def test_o_relatorio_carrega_a_procedencia(self, settings: Settings) -> None:
        pares = _pares(limite=1)
        provedor = ProvedorDeGabarito(modulo.casos_de(pares))
        medidas = _mede_par(pares[0], provedor, settings)

        assert _resume(medidas, settings, pares)["corpus"]["limpo"]["semente"] is not None


class TestFlagNoEval:
    def test_o_eval_de_boleto_e_o_padrao(self) -> None:
        """Informe é corpus adicional, não substituto."""
        import eval as modulo_eval

        assert not modulo_eval._analisa_argumentos([]).informes
        assert modulo_eval._analisa_argumentos(["--informes"]).informes

    def test_a_flag_desvia_para_o_eval_de_informe(self, monkeypatch: Any) -> None:
        import eval as modulo_eval

        chamados: list[str] = []

        def informe(_: Any) -> int:
            chamados.append("informe")
            return 0

        def boleto(*_: Any, **__: Any) -> list[Any]:
            chamados.append("boleto")
            return []

        monkeypatch.setattr(modulo_eval, "main_informe", informe)
        monkeypatch.setattr(modulo_eval, "roda", boleto)

        modulo_eval.main(["--informes"])

        assert chamados == ["informe"]

    def test_os_dois_relatorios_vao_para_o_mesmo_diretorio(self) -> None:
        """E se distinguem pelo campo `documento`, não pelo caminho."""
        assert modulo_relatorio.DIRETORIO_RESULTADOS == Path("resultados")
