"""Extração de boleto: do documento ingerido ao dado, com a evidência junto.

A extração não decide nada. Ela produz três coisas para os sinais de
confiança olharem depois: o que o modelo escreveu (`bruto`), o que isso vira
no domínio (`dominio`, ou `None` se não fechar) e o que a chamada custou.

O caminho de visão é **recusado aqui**, de propósito. Ver ADR 005.
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from app.confianca import normalizacao
from app.dominio.boleto import Boleto
from app.extracao.prompt import Prompt, carrega
from app.extracao.schema_transporte import BoletoExtraido
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


def para_dominio(bruto: BoletoExtraido) -> tuple[Boleto | None, str | None]:
    """Converte o transporte em `Boleto`. A falha aqui é o sinal de DV.

    Não tenta consertar nada: se o modelo escreveu um valor que não bate com
    a linha digitável, a conversão reprova, e é exatamente esse o ponto.
    """
    valor = normalizacao.numero(bruto.valor)
    vencimento = normalizacao.data(bruto.vencimento)
    if valor is None or vencimento is None:
        faltando = [
            nome for nome, lido in (("valor", valor), ("vencimento", vencimento)) if lido is None
        ]
        return None, f"não deu para ler {', '.join(faltando)} do que o modelo devolveu"

    campos = {
        "linha_digitavel": normalizacao.digitos(bruto.linha_digitavel),
        "beneficiario_nome": bruto.beneficiario_nome.strip(),
        "beneficiario_cnpj": normalizacao.digitos(bruto.beneficiario_cnpj),
        "pagador_nome": bruto.pagador_nome.strip() or None,
        "pagador_cpf_cnpj": normalizacao.digitos(bruto.pagador_cpf_cnpj) or None,
        "valor": valor,
        "vencimento": vencimento,
        "banco_codigo": normalizacao.digitos(bruto.banco_codigo),
        "banco_nome": bruto.banco_nome.strip(),
        "nosso_numero": bruto.nosso_numero.strip() or None,
    }
    try:
        return Boleto.model_validate(campos), None
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
