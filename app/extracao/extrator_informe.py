"""Extração de informe: do documento ingerido ao dado, com a evidência junto.

Mesma divisão de trabalho do extrator de boleto — a extração não decide nada,
só produz o que os sinais vão olhar — e as mesmas três saídas: o que o modelo
escreveu (`bruto`), o que isso vira no domínio (`dominio`, ou `None`) e o que
a chamada custou.

## A quarta saída, que o boleto não tinha

`conferencias` é a aritmética de cada quadro, calculada **sobre o que o modelo
escreveu**, e não sobre o `Informe` já validado. A diferença importa: o
`Informe` recusa a instância inteira quando um quadro diverge ou quando duas
linhas repetem o identificador, e é exatamente aí que a aritmética tem algo a
dizer. Se ela dependesse do domínio ter fechado, ficaria muda nos dois ataques
que só ela pega — `total_adulterado` e `quadro_duplicado`. Então ela é
calculada antes, direto do transporte, com a mesma função de soma que o
domínio usa (`app.dominio.informe.confere_soma`).

## Cobertura não é aprovação

`conferencias` distingue três coisas, e a política precisa das três: quadro
que fechou, quadro que não fechou, e quadro que **não tinha total para
conferir**. O terceiro não é aprovação — é o mesmo caso do PDF sem camada de
texto da Fase 1.2, e o ADR 009 o trata igual. Ver `app.confianca.politica_informe`.

O caminho de visão é recusado aqui, como no boleto e pela mesma razão (ADR 005).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.confianca import campos
from app.dominio.informe import (
    CAMPOS_DE_LINHA,
    CAMPOS_DE_SALDO,
    ConferenciaDeQuadro,
    Informe,
    Layout,
    confere_soma,
)
from app.extracao.extrator import ExtracaoPorVisaoNaoSuportada
from app.extracao.prompt import PROMPT_INFORME, Prompt, carrega
from app.extracao.schema_transporte_informe import (
    CAMPOS,
    InformeExtraido,
    QuadroExtraido,
)
from app.ingestao.documento import DocumentoIngerido
from app.llm.provedor import ProvedorLLM, UsoDeTokens

LAYOUTS = tuple(layout.value for layout in Layout)


@dataclass(frozen=True, slots=True)
class ExtracaoDeInforme:
    """O resultado de uma extração de informe, com a evidência que os sinais usam."""

    documento: Path
    prompt: Prompt
    bruto: InformeExtraido
    """O que o modelo escreveu, sem conversão. É o que o grounding confere."""

    dominio: Informe | None
    """O informe validado, ou None quando os validadores do ADR 007 reprovam."""

    erro_de_dominio: str | None
    conferencias: tuple[ConferenciaDeQuadro, ...]
    """A aritmética de cada quadro, calculada sobre o transporte. Ver o módulo."""

    provedor: str
    modelo: str
    uso: UsoDeTokens
    custo_estimado_usd: Decimal
    do_cache: bool

    @property
    def fecha_no_dominio(self) -> bool:
        """DV do CNPJ e do CPF, exercício e somas, em uma palavra."""
        return self.dominio is not None

    @property
    def quadros_conferidos(self) -> tuple[ConferenciaDeQuadro, ...]:
        return tuple(c for c in self.conferencias if c.tem_cobertura)

    @property
    def quadros_divergentes(self) -> tuple[ConferenciaDeQuadro, ...]:
        return tuple(c for c in self.conferencias if c.divergiu)

    @property
    def aritmetica_teve_cobertura(self) -> bool:
        """Algum quadro tinha total impresso contra o que conferir a soma.

        Falso não quer dizer "está certo": quer dizer que ninguém conferiu.
        """
        return bool(self.quadros_conferidos)

    def descricao_da_aritmetica(self) -> str:
        if self.quadros_divergentes:
            return "; ".join(c.descricao() for c in self.quadros_divergentes)
        if not self.aritmetica_teve_cobertura:
            sem = ", ".join(c.quadro for c in self.conferencias) or "nenhum quadro"
            return f"nenhum quadro tinha total impresso para conferir ({sem})"
        conferidos = ", ".join(c.quadro for c in self.quadros_conferidos)
        return f"soma confere nos quadros com total impresso: {conferidos}"


def _decimal_ou_none(texto: str) -> Decimal | None:
    """O valor canônico como Decimal, ou None quando o texto não é número."""
    try:
        return Decimal(campos.canonico("valor", texto))
    except (campos.ValorIlegivel, InvalidOperation):
        return None


def confere_quadros(bruto: InformeExtraido) -> tuple[ConferenciaDeQuadro, ...]:
    """A aritmética de cada quadro, sobre os números que o modelo escreveu.

    Linha cujo valor não é número legível conta como zero na soma **e** é
    reportada pelo domínio como ilegível: aqui o objetivo é não perder a
    conferência dos outros quadros por causa de uma linha ruim, e quem reprova
    o documento por ela é `para_dominio`.
    """
    conferencias = []
    for nome, quadro in bruto.quadros():
        valores = [
            valor for linha in quadro.linhas if (valor := _decimal_ou_none(linha.valor)) is not None
        ]
        total = _decimal_ou_none(quadro.total_impresso) if quadro.total_impresso.strip() else None
        conferencias.append(confere_soma(nome, valores, total))
    return tuple(conferencias)


def _linhas_do_quadro(nome: str, quadro: QuadroExtraido, erros: list[str]) -> list[dict[str, Any]]:
    linhas = []
    for indice, linha in enumerate(quadro.linhas, 1):
        onde = f"{nome}[{indice}]"
        if not linha.identificador.strip():
            erros.append(f"{onde}: linha sem identificador, que é a chave de casamento")
            continue
        try:
            valor = campos.canonico("valor", linha.valor)
        except campos.ValorIlegivel as erro:
            erros.append(f"{onde} ({linha.identificador}): {erro}")
            continue
        linhas.append(
            {
                "identificador": linha.identificador.strip(),
                "descricao": linha.descricao.strip(),
                "valor": valor,
            }
        )
    return linhas


def _saldos(bruto: InformeExtraido, erros: list[str]) -> list[dict[str, Any]]:
    saldos = []
    for indice, saldo in enumerate(bruto.saldos, 1):
        onde = f"saldos[{indice}]"
        if not saldo.especificacao.strip():
            erros.append(f"{onde}: saldo sem especificação, que é a chave do cruzamento")
            continue
        convertidos: dict[str, Any] = {"especificacao": saldo.especificacao.strip()}
        for campo in CAMPOS_DE_SALDO:
            try:
                convertidos[campo] = campos.canonico(campo, getattr(saldo, campo))
            except campos.ValorIlegivel as erro:
                erros.append(f"{onde} ({saldo.especificacao}): {campo}: {erro}")
        if len(convertidos) == len(CAMPOS_DE_SALDO) + 1:
            saldos.append(convertidos)
    return saldos


def para_dominio(bruto: InformeExtraido) -> tuple[Informe | None, str | None]:
    """Converte o transporte em `Informe`. A falha aqui é o sinal do ADR 007.

    A forma canônica de cada campo vem de `app.confianca.campos`, o mesmo
    módulo que o grounding e o eval consultam — a definição de igualdade mora
    num lugar só (ADR 005).

    Não conserta nada além da forma. Se o modelo escreveu um exercício que não
    é o ano-calendário mais um, ou um CNPJ cujo DV não fecha, ou um quadro cuja
    soma não bate com o total que ele mesmo transcreveu, a conversão reprova, e
    é esse o ponto.
    """
    erros: list[str] = []
    valores: dict[str, Any] = {}

    if bruto.layout.strip() not in LAYOUTS:
        erros.append(
            f"layout {bruto.layout.strip()!r} não é um dos dois conhecidos ({', '.join(LAYOUTS)})"
        )
    else:
        valores["layout"] = bruto.layout.strip()

    for campo in CAMPOS:
        if campo == "layout":
            continue
        escrito = getattr(bruto, campo).strip()
        if not escrito:
            erros.append(f"o modelo não preencheu: {campo}")
            continue
        try:
            valores[campo] = campos.canonico(campo, escrito)
        except campos.ValorIlegivel as erro:
            erros.append(str(erro))

    for nome, quadro in bruto.quadros():
        total = quadro.total_impresso.strip()
        convertido: dict[str, Any] = {
            "identificador": nome,
            "linhas": _linhas_do_quadro(nome, quadro, erros),
            "total_impresso": None,
        }
        if total:
            try:
                convertido["total_impresso"] = campos.canonico("total_impresso", total)
            except campos.ValorIlegivel as erro:
                erros.append(f"{nome}: total impresso: {erro}")
        valores[nome] = convertido

    valores["saldos"] = _saldos(bruto, erros)

    if erros:
        return None, "; ".join(erros)

    try:
        return Informe.model_validate(valores), None
    except ValidationError as erro:
        motivos = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'informe'}: {e['msg']}" for e in erro.errors()
        )
        return None, motivos


def extrai(
    documento: DocumentoIngerido,
    provedor: ProvedorLLM,
    *,
    prompt: Prompt | None = None,
) -> ExtracaoDeInforme:
    """Pede a extração ao modelo e converte o que voltou.

    O texto vai ao provedor, que o embrulha nos delimitadores de isolamento da
    Fase 1.2 — o isolamento é responsabilidade do provedor e acontece para
    qualquer chamada, não só para esta.
    """
    if documento.por_visao:
        raise ExtracaoPorVisaoNaoSuportada(
            f"{documento.caminho.name} não tem camada de texto. "
            "O caminho de visão está aberto na ingestão mas fechado aqui, "
            "porque a sanitização da Fase 1.2 não tem cobertura sobre imagem."
        )

    usado = prompt if prompt is not None else carrega(PROMPT_INFORME)
    resultado = provedor.extrai(documento.texto, InformeExtraido, instrucao=usado.texto)
    dominio, erro = para_dominio(resultado.dados)

    return ExtracaoDeInforme(
        documento=documento.caminho,
        prompt=usado,
        bruto=resultado.dados,
        dominio=dominio,
        erro_de_dominio=erro,
        conferencias=confere_quadros(resultado.dados),
        provedor=resultado.provedor,
        modelo=resultado.modelo,
        uso=resultado.uso,
        custo_estimado_usd=resultado.custo_estimado_usd,
        do_cache=resultado.do_cache,
    )


@dataclass(frozen=True, slots=True)
class ValorExtraido:
    """Um valor que o modelo escreveu, com o campo e o lugar de onde ele veio.

    Existe porque o informe é uma árvore e os dois sinais que precisam
    percorrê-la — grounding e auto-consistência — precisam de coisas
    diferentes do mesmo passeio. O grounding quer o **campo**, para saber como
    procurar o valor no texto (dígito procura em dígito, valor procura nas
    formas em que ele pode estar impresso). A auto-consistência quer o
    **lugar**, para poder comparar duas execuções sem depender da ordem em que
    cada uma devolveu as linhas.

    `local` é único dentro de um informe, e é montado a partir da chave da
    linha, não do índice: um modelo que devolve as mesmas linhas em outra ordem
    leu o documento certo, e penalizá-lo por isso mediria formatação.
    """

    campo: str
    valor: str
    local: str


def _local_unico(base: str, usados: set[str]) -> str:
    """Desempata chave repetida. Repetir é o `quadro_duplicado`, e ele tem de aparecer."""
    local, repeticao = base, 2
    while local in usados:
        local, repeticao = f"{base}#{repeticao}", repeticao + 1
    usados.add(local)
    return local


def valores_extraidos(bruto: InformeExtraido) -> tuple[ValorExtraido, ...]:
    """Achata o informe extraído em valores endereçáveis, sem converter nada."""
    valores: list[ValorExtraido] = []
    usados: set[str] = set()

    for campo in CAMPOS:
        valores.append(ValorExtraido(campo, getattr(bruto, campo), campo))

    for nome, quadro in bruto.quadros():
        for indice, linha in enumerate(quadro.linhas, 1):
            chave = linha.identificador.strip() or f"#{indice}"
            base = _local_unico(f"{nome}[{chave}]", usados)
            valores.append(ValorExtraido("identificador", linha.identificador, f"{base}.chave"))
            for campo in CAMPOS_DE_LINHA:
                valores.append(ValorExtraido(campo, getattr(linha, campo), f"{base}.{campo}"))
        valores.append(
            ValorExtraido("total_impresso", quadro.total_impresso, f"{nome}.total_impresso")
        )

    for indice, saldo in enumerate(bruto.saldos, 1):
        chave = saldo.especificacao.strip() or f"#{indice}"
        base = _local_unico(f"saldos[{chave}]", usados)
        valores.append(ValorExtraido("especificacao", saldo.especificacao, f"{base}.chave"))
        for campo in CAMPOS_DE_SALDO:
            valores.append(ValorExtraido(campo, getattr(saldo, campo), f"{base}.{campo}"))

    return tuple(valores)


def como_mapa(bruto: InformeExtraido) -> dict[str, str]:
    """O informe extraído como lugar → valor, para comparar duas execuções."""
    return {valor.local: valor.valor.strip() for valor in valores_extraidos(bruto)}


def linhas_por_quadro(bruto: InformeExtraido) -> dict[str, Sequence[dict[str, str]]]:
    """As linhas de cada quadro como texto, para as métricas de linha.

    Devolve o que o modelo escreveu, sem conversão: quem compara é
    `app.confianca.campos.iguais`, e ela precisa dos dois lados como texto.
    """
    return {
        nome: [
            {
                "identificador": linha.identificador,
                "descricao": linha.descricao,
                "valor": linha.valor,
            }
            for linha in quadro.linhas
        ]
        for nome, quadro in bruto.quadros()
    }
