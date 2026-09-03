"""Extração de boleto: do documento ingerido ao dado, com a evidência junto.

A extração não decide nada. Ela produz três coisas para os sinais de
confiança olharem depois: o que o modelo escreveu (`bruto`), o que isso vira
no domínio (`dominio`, ou `None` se não fechar) e o que a chamada custou.

O caminho de visão é **recusado aqui**, de propósito. Ver ADR 005.
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.confianca import campos
from app.dominio.boleto import Boleto
from app.extracao.prompt import Prompt, carrega
from app.extracao.schema_transporte import CAMPOS, BoletoExtraido
from app.ingestao.documento import DocumentoIngerido
from app.llm.provedor import ProvedorLLM, UsoDeTokens


class ExtracaoPorVisaoNaoSuportada(NotImplementedError):
    """O documento não tem camada de texto e o caminho de visão não está aberto.

    Não é esquecimento: mandar a imagem de um documento não confiável ao
    modelo abriria uma superfície que nenhum detector da Fase 1.2 cobre, e o
    ADR 004 registrou que essa defesa tem que ser desenhada junto com o
    caminho. Enquanto ela não existir, o documento vai para revisão humana em
    vez de ser extraído sem rede. Ver ADR 005.
    """


@dataclass(frozen=True, slots=True)
class Extracao:
    """O resultado de uma extração, com a evidência que os sinais precisam."""

    documento: Path
    prompt: Prompt
    bruto: BoletoExtraido
    """O que o modelo escreveu, sem conversão. É o que o grounding confere."""

    dominio: Boleto | None
    """O boleto validado, ou None quando a validação cruzada do ADR 002 reprova."""

    erro_de_dominio: str | None
    provedor: str
    modelo: str
    uso: UsoDeTokens
    custo_estimado_usd: Decimal
    do_cache: bool

    @property
    def fecha_no_dominio(self) -> bool:
        """O sinal de dígito verificador, em uma palavra."""
        return self.dominio is not None


OPCIONAIS = frozenset({"pagador_nome", "pagador_cpf_cnpj", "nosso_numero"})


def para_dominio(bruto: BoletoExtraido) -> tuple[Boleto | None, str | None]:
    """Converte o transporte em `Boleto`. A falha aqui é o sinal de DV.

    A forma canônica de cada campo vem de `app.confianca.campos`, o mesmo
    módulo que o grounding e o eval consultam. Se ela morasse aqui, o eval
    precisaria repeti-la — e foi exatamente assim que uma taxa de escape
    falsa de 50% nasceu (ADR 005).

    Não conserta nada além da forma: se o modelo escreveu um valor que não
    bate com a linha digitável, a conversão reprova, e é esse o ponto.
    """
    ilegiveis: list[str] = []
    canonicos: dict[str, str] = {}
    for campo in CAMPOS:
        escrito = getattr(bruto, campo).strip()
        if not escrito:
            continue
        try:
            canonicos[campo] = campos.canonico(campo, escrito)
        except campos.ValorIlegivel as erro:
            ilegiveis.append(str(erro))

    if ilegiveis:
        return None, "; ".join(ilegiveis)

    faltando = [c for c in CAMPOS if c not in canonicos and c not in OPCIONAIS]
    if faltando:
        return None, f"o modelo não preencheu: {', '.join(faltando)}"

    valores: dict[str, Any] = dict(canonicos)
    for campo in OPCIONAIS:
        valores.setdefault(campo, None)

    try:
        return Boleto.model_validate(valores), None
    except ValidationError as erro:
        motivos = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'boleto'}: {e['msg']}" for e in erro.errors()
        )
        return None, motivos


def extrai(
    documento: DocumentoIngerido,
    provedor: ProvedorLLM,
    *,
    prompt: Prompt | None = None,
) -> Extracao:
    """Pede a extração ao modelo e converte o que voltou.

    O texto vai ao provedor, que o embrulha nos delimitadores de isolamento
    da Fase 1.2 — o isolamento é responsabilidade do provedor e acontece para
    qualquer chamada, não só para esta.
    """
    if documento.por_visao:
        raise ExtracaoPorVisaoNaoSuportada(
            f"{documento.caminho.name} não tem camada de texto. "
            "O caminho de visão está aberto na ingestão mas fechado aqui, "
            "porque a sanitização da Fase 1.2 não tem cobertura sobre imagem."
        )

    usado = prompt if prompt is not None else carrega()
    resultado = provedor.extrai(documento.texto, BoletoExtraido, instrucao=usado.texto)
    dominio, erro = para_dominio(resultado.dados)

    return Extracao(
        documento=documento.caminho,
        prompt=usado,
        bruto=resultado.dados,
        dominio=dominio,
        erro_de_dominio=erro,
        provedor=resultado.provedor,
        modelo=resultado.modelo,
        uso=resultado.uso,
        custo_estimado_usd=resultado.custo_estimado_usd,
        do_cache=resultado.do_cache,
    )
