"""Do resultado do pipeline para as linhas do banco.

Fica fora dos pipelines de propósito. `app/pipeline.py` e
`app/pipeline_informe.py` não sabem que existe banco, não importam SQLAlchemy e
não mudaram nesta fase — o eval continua processando 56 documentos sem abrir
conexão nenhuma.

Quem chama isto é a API, e é ela que decide persistir. A tradução é de mão
única: lê o resultado em memória e escreve linhas. Nada aqui volta para o
pipeline.

## Onde os quatro estados são decididos

`_estado` é a única função do projeto que converte `Veredito` em
`EstadoDoSinal`, e é a razão de este módulo existir separado. A conversão tem
uma armadilha: `executou=False` significa duas coisas diferentes conforme
`dispensado`, e colapsar as duas é exatamente o que o ADR 009 proíbe.
"""

import hashlib
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from app.confianca.politica import DecisaoFinal, Veredito
from app.confianca.politica import Rota as RotaDaPolitica
from app.extracao.extrator import Extracao as ExtracaoDeBoleto
from app.extracao.extrator_informe import ExtracaoDeInforme
from app.ingestao.documento import DocumentoIngerido
from app.persistencia.modelos import (
    Achado,
    Correcao,
    Decisao,
    Documento,
    EstadoDoSinal,
    Extracao,
    Rota,
    Sinal,
    TipoDeDocumento,
)
from app.seguranca.sanitizador import Achado as AchadoDaSanitizacao

QualquerExtracao = ExtracaoDeBoleto | ExtracaoDeInforme


def hash_do_arquivo(caminho: Path) -> str:
    """SHA-256 do conteúdo, que é a identidade do documento.

    O caminho não serve como identidade: o mesmo arquivo é reprocessado, e o
    mesmo conteúdo chega por caminhos diferentes.
    """
    digest = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 20), b""):
            digest.update(bloco)
    return digest.hexdigest()


def _estado(veredito: Veredito) -> EstadoDoSinal:
    """Converte um veredito nos quatro estados gravados.

    A ordem dos testes é a armadilha. `executou=False` significa duas coisas
    diferentes: o operador desligou o sinal (`dispensado`), ou o sinal não teve
    o que conferir. A primeira não bloqueia, a segunda bloqueia — e é a regra
    que o ADR 009 fixou. Testar `dispensado` antes é o que mantém as duas
    separadas.
    """
    if veredito.dispensado:
        return EstadoDoSinal.DISPENSADO
    if not veredito.executou:
        return EstadoDoSinal.SEM_COBERTURA
    return EstadoDoSinal.CONFERIDO if veredito.aprovou else EstadoDoSinal.DIVERGENTE


def _decimal(valor: float) -> Decimal:
    """Latência vem como float do `time.monotonic`; dinheiro nunca passa por aqui."""
    return Decimal(str(round(valor, 3)))


def registra_documento(
    sessao: Session,
    caminho: Path,
    tipo: TipoDeDocumento,
    *,
    paginas: int | None = None,
) -> Documento:
    """Grava o documento, ou devolve o que já existe com o mesmo conteúdo.

    Reprocessar não cria documento novo: o hash é a identidade, e duas linhas
    para o mesmo conteúdo espalhariam as correções entre elas.
    """
    digest = hash_do_arquivo(caminho)
    existente = (
        sessao.query(Documento)
        .filter(Documento.hash_sha256 == digest)
        .order_by(Documento.id)
        .first()
    )
    if existente is not None:
        return existente

    documento = Documento(
        arquivo=str(caminho),
        hash_sha256=digest,
        tipo=tipo,
        paginas=paginas,
    )
    sessao.add(documento)
    sessao.flush()
    return documento


def _grava_extracao(sessao: Session, documento: Documento, extracao: QualquerExtracao) -> Extracao:
    linha = Extracao(
        documento_id=documento.id,
        payload=extracao.bruto.model_dump(mode="json"),
        prompt=extracao.prompt.identificador,
        provedor=extracao.provedor,
        modelo=extracao.modelo,
        tokens_entrada=extracao.uso.entrada,
        tokens_saida=extracao.uso.saida,
        custo_usd=extracao.custo_estimado_usd,
        do_cache=extracao.do_cache,
        erro_de_dominio=extracao.erro_de_dominio,
    )
    sessao.add(linha)
    sessao.flush()
    return linha


def _grava_achados(
    sessao: Session, decisao: Decisao, achados: tuple[AchadoDaSanitizacao, ...]
) -> None:
    for achado in achados:
        sessao.add(
            Achado(
                decisao_id=decisao.id,
                tipo=achado.tipo.value,
                severidade=achado.severidade.value,
                trecho=achado.trecho,
                detalhe=achado.detalhe,
                pagina=achado.local.pagina,
                x0=None if achado.local.x0 is None else _decimal(achado.local.x0),
                topo=None if achado.local.topo is None else _decimal(achado.local.topo),
                x1=None if achado.local.x1 is None else _decimal(achado.local.x1),
                base=None if achado.local.base is None else _decimal(achado.local.base),
            )
        )


def _escopos_do_grounding(decisao_final: DecisaoFinal) -> tuple[str, ...]:
    """Os lugares que o grounding reprovou, já calculados pela política."""
    return decisao_final.campos_a_revisar


def grava(
    sessao: Session,
    *,
    caminho: Path,
    tipo: TipoDeDocumento,
    ingestao: DocumentoIngerido,
    decisao_final: DecisaoFinal,
    extracao: QualquerExtracao | None,
    latencia_s: float,
) -> Decisao:
    """Grava um processamento inteiro: documento, extração, sinais e decisão.

    Devolve a `Decisao`, que é a linha que a fila de revisão lista.
    """
    # A ingestão só conta páginas no caminho de visão, onde ela rasteriza uma
    # por uma. No caminho de texto o número não é conhecido, e `None` diz isso
    # — zero diria "documento sem página", que é outra coisa.
    paginas = len(ingestao.paginas_png) or None
    documento = registra_documento(sessao, caminho, tipo, paginas=paginas)

    linha_de_extracao = (
        _grava_extracao(sessao, documento, extracao) if extracao is not None else None
    )
    if linha_de_extracao is not None:
        linha_de_extracao.latencia_s = _decimal(latencia_s)

    decisao = Decisao(
        documento_id=documento.id,
        extracao_id=linha_de_extracao.id if linha_de_extracao is not None else None,
        rota=(
            Rota.AUTO_APROVADO
            if decisao_final.rota is RotaDaPolitica.AUTO_APROVADO
            else Rota.REVISAO_HUMANA
        ),
    )
    sessao.add(decisao)
    sessao.flush()

    for veredito in decisao_final.vereditos:
        sessao.add(
            Sinal(
                decisao_id=decisao.id,
                nome=veredito.sinal.value,
                estado=_estado(veredito),
                detalhe=veredito.detalhe,
            )
        )

    # O grounding é o único sinal com endereço, e a política já apurou quais
    # lugares precisam de revisão. Gravá-los como linhas próprias é o que
    # permite à tela listar "onde olhar" sem reabrir o payload.
    for escopo in _escopos_do_grounding(decisao_final):
        sessao.add(
            Sinal(
                decisao_id=decisao.id,
                nome="campo_a_revisar",
                estado=EstadoDoSinal.DIVERGENTE,
                detalhe="apontado por grounding, consistência ou aritmética",
                escopo=escopo,
            )
        )

    _grava_achados(sessao, decisao, ingestao.sanitizacao.achados)
    sessao.flush()
    return decisao


def grava_correcao(
    sessao: Session,
    *,
    decisao: Decisao,
    campo: str,
    valor_anterior: str,
    valor_corrigido: str,
    revisor: str = "",
) -> Correcao:
    """Grava a correção de um campo. Uma por campo e decisão — ver a unicidade."""
    correcao = Correcao(
        documento_id=decisao.documento_id,
        decisao_id=decisao.id,
        campo=campo,
        valor_anterior=valor_anterior,
        valor_corrigido=valor_corrigido,
        revisor=revisor,
    )
    sessao.add(correcao)
    sessao.flush()
    return correcao
