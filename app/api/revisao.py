"""A API da fila de revisão. Sem interface ainda — só o que a tela vai consumir.

Quatro capacidades, e nenhuma a mais: listar a fila, abrir um documento com o
diagnóstico completo, submeter correções e ver as estatísticas.

## O que esta API não faz

**Não processa documento.** Extrair é do pipeline, custa cota e demora dezenas
de segundos; um endpoint que chamasse o modelo transformaria a tela de revisão
numa porta para gastar orçamento. O que ela lê já foi processado e gravado.

**Não recalcula sinal.** Os vereditos vêm do banco como o pipeline os deixou.
Recalcular na leitura abriria a possibilidade de a tela mostrar uma coisa e o
histórico guardar outra — e a diferença apareceria como revisor discordando de
si mesmo entre duas aberturas da mesma página.
"""

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencias import SessaoDependente
from app.api.esquemas import (
    AchadoNaResposta,
    Caixa,
    CorrecaoNaResposta,
    Diagnostico,
    EstatisticasDaFila,
    ExtracaoNaResposta,
    ItemDaFila,
    Pagina,
    PedidoDeCorrecao,
    RespostaDeCorrecao,
    SinalNaResposta,
)
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
    agora,
)

roteador = APIRouter(prefix="/revisao", tags=["revisão"])

ESTADOS_QUE_BLOQUEIAM = (EstadoDoSinal.DIVERGENTE, EstadoDoSinal.SEM_COBERTURA)

LIMITE_PADRAO = 50
LIMITE_MAXIMO = 200


def _decisao_completa(sessao: Session, decisao_id: int) -> Decisao:
    """Carrega a decisão com tudo que o diagnóstico precisa, numa consulta.

    `selectinload` em vez de lazy: sem ele, montar a resposta dispararia uma
    consulta por relação, e o diagnóstico tem quatro.
    """
    decisao = sessao.scalars(
        select(Decisao)
        .where(Decisao.id == decisao_id)
        .options(
            selectinload(Decisao.sinais),
            selectinload(Decisao.documento).selectinload(Documento.correcoes),
            selectinload(Decisao.extracao),
        )
    ).one_or_none()

    if decisao is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"decisão {decisao_id} não existe",
        )
    return decisao


def _achados(sessao: Session, decisao_id: int) -> list[Achado]:
    return list(
        sessao.scalars(select(Achado).where(Achado.decisao_id == decisao_id).order_by(Achado.id))
    )


def _item(decisao: Decisao, sinais: Sequence[Sinal], achados: int) -> ItemDaFila:
    bloqueiam = [s for s in sinais if s.estado.bloqueia]
    return ItemDaFila(
        decisao_id=decisao.id,
        documento_id=decisao.documento_id,
        arquivo=decisao.documento.arquivo,
        tipo=decisao.documento.tipo,
        rota=decisao.rota,
        criada_em=decisao.criada_em,
        revisada_em=decisao.revisada_em,
        sinais_que_bloqueiam=[s.nome for s in bloqueiam if s.escopo is None],
        sem_cobertura=[
            s.nome
            for s in bloqueiam
            if s.escopo is None and s.estado is EstadoDoSinal.SEM_COBERTURA
        ],
        achados=achados,
    )


@roteador.get("/fila", response_model=Pagina)
def lista_fila(
    sessao: SessaoDependente,
    tipo: Annotated[TipoDeDocumento | None, Query(description="boleto ou informe")] = None,
    sinal: Annotated[
        str | None,
        Query(
            description=(
                "só documentos em que este sinal bloqueou — reprovou ou não teve "
                "o que conferir. Ex.: aritmetica, cruzamento, sanitizacao"
            )
        ),
    ] = None,
    estado: Annotated[
        EstadoDoSinal | None,
        Query(
            description=(
                "combina com `sinal` para separar 'reprovou' de 'não teve o que "
                "conferir'. São filas de trabalho diferentes"
            )
        ),
    ] = None,
    pendentes: Annotated[bool, Query(description="só o que ainda não foi revisado")] = True,
    deslocamento: Annotated[int, Query(ge=0)] = 0,
    limite: Annotated[int, Query(ge=1, le=LIMITE_MAXIMO)] = LIMITE_PADRAO,
) -> Pagina:
    """A fila, filtrável por tipo e pelo sinal que barrou o documento."""
    consulta = (
        select(Decisao)
        .join(Documento, Decisao.documento_id == Documento.id)
        .where(Decisao.rota == Rota.REVISAO_HUMANA)
    )
    if tipo is not None:
        consulta = consulta.where(Documento.tipo == tipo)
    if pendentes:
        consulta = consulta.where(Decisao.revisada_em.is_(None))
    if sinal is not None or estado is not None:
        condicao = select(Sinal.decisao_id).where(
            Sinal.estado.in_(ESTADOS_QUE_BLOQUEIAM if estado is None else [estado])
        )
        if sinal is not None:
            condicao = condicao.where(Sinal.nome == sinal)
        consulta = consulta.where(Decisao.id.in_(condicao))

    total = sessao.scalar(select(func.count()).select_from(consulta.subquery())) or 0

    pagina = sessao.scalars(
        consulta.order_by(Decisao.criada_em.desc(), Decisao.id.desc())
        .offset(deslocamento)
        .limit(limite)
        .options(selectinload(Decisao.sinais), selectinload(Decisao.documento))
    ).all()

    # Uma consulta agregada para a página inteira, e não uma por item: a lista
    # é o lugar onde N+1 aparece primeiro.
    quantidade_de_achados: dict[int, int] = {
        decisao_id: quantos
        for decisao_id, quantos in sessao.execute(
            select(Achado.decisao_id, func.count())
            .where(Achado.decisao_id.in_([d.id for d in pagina] or [0]))
            .group_by(Achado.decisao_id)
        ).all()
    }

    return Pagina(
        itens=[
            _item(decisao, decisao.sinais, quantidade_de_achados.get(decisao.id, 0))
            for decisao in pagina
        ],
        total=total,
        deslocamento=deslocamento,
        limite=limite,
    )


@roteador.get("/estatisticas", response_model=EstatisticasDaFila)
def estatisticas(sessao: SessaoDependente) -> EstatisticasDaFila:
    """Os números da fila, com as duas contagens que não podem virar uma."""
    decisoes = list(
        sessao.scalars(
            select(Decisao).options(selectinload(Decisao.sinais), selectinload(Decisao.documento))
        )
    )
    na_fila = [d for d in decisoes if d.rota is Rota.REVISAO_HUMANA]

    por_tipo: dict[str, int] = {}
    por_sinal: dict[str, int] = {}
    so_falta_de_cobertura = 0
    for decisao in na_fila:
        por_tipo[decisao.documento.tipo.value] = por_tipo.get(decisao.documento.tipo.value, 0) + 1
        bloqueadores = [s for s in decisao.sinais if s.estado.bloqueia and s.escopo is None]
        for sinal in bloqueadores:
            por_sinal[sinal.nome] = por_sinal.get(sinal.nome, 0) + 1
        if bloqueadores and all(s.estado is EstadoDoSinal.SEM_COBERTURA for s in bloqueadores):
            so_falta_de_cobertura += 1

    correcoes = list(sessao.scalars(select(Correcao)))
    mais_corrigidos: dict[str, int] = {}
    for correcao in correcoes:
        mais_corrigidos[correcao.campo] = mais_corrigidos.get(correcao.campo, 0) + 1

    custo = sessao.scalar(select(func.coalesce(func.sum(Extracao.custo_usd), 0))) or Decimal("0")

    return EstatisticasDaFila(
        total=len(decisoes),
        pendentes=sum(1 for d in na_fila if d.revisada_em is None),
        revisados=sum(1 for d in na_fila if d.revisada_em is not None),
        auto_aprovados=sum(1 for d in decisoes if d.rota is Rota.AUTO_APROVADO),
        por_tipo=por_tipo,
        por_sinal_que_bloqueia=dict(sorted(por_sinal.items())),
        bloqueados_so_por_falta_de_cobertura=so_falta_de_cobertura,
        correcoes=len(correcoes),
        campos_mais_corrigidos=dict(
            sorted(mais_corrigidos.items(), key=lambda par: (-par[1], par[0]))
        ),
        custo_total_usd=Decimal(custo),
    )


@roteador.get("/{decisao_id}", response_model=Diagnostico)
def diagnostico(decisao_id: int, sessao: SessaoDependente) -> Diagnostico:
    """Tudo que o pipeline sabe sobre este documento.

    É o que a tela abre, e é o que diferencia esta rota de um CRUD: os quatro
    estados por sinal, a mensagem que aponta a causa, e os trechos suspeitos
    com a página e as coordenadas.
    """
    decisao = _decisao_completa(sessao, decisao_id)
    extracao = decisao.extracao

    return Diagnostico(
        decisao_id=decisao.id,
        documento_id=decisao.documento_id,
        arquivo=decisao.documento.arquivo,
        hash_sha256=decisao.documento.hash_sha256,
        tipo=decisao.documento.tipo,
        rota=decisao.rota,
        ingerido_em=decisao.documento.ingerido_em,
        criada_em=decisao.criada_em,
        revisada_em=decisao.revisada_em,
        extracao=(
            None
            if extracao is None
            else ExtracaoNaResposta(
                payload=extracao.payload,
                prompt=extracao.prompt,
                provedor=extracao.provedor,
                modelo=extracao.modelo,
                tokens_entrada=extracao.tokens_entrada,
                tokens_saida=extracao.tokens_saida,
                custo_usd=extracao.custo_usd,
                latencia_s=extracao.latencia_s,
                do_cache=extracao.do_cache,
                erro_de_dominio=extracao.erro_de_dominio,
            )
        ),
        sinais=[SinalNaResposta.de_linha(s) for s in decisao.sinais],
        achados=[
            AchadoNaResposta(
                tipo=a.tipo,
                severidade=a.severidade,
                trecho=a.trecho,
                detalhe=a.detalhe,
                pagina=a.pagina,
                caixa=Caixa(x0=a.x0, topo=a.topo, x1=a.x1, base=a.base),
            )
            for a in _achados(sessao, decisao_id)
        ],
        correcoes=[
            CorrecaoNaResposta.model_validate(c)
            for c in decisao.documento.correcoes
            if c.decisao_id == decisao.id
        ],
    )


@roteador.get("/{decisao_id}/pdf")
def pdf(decisao_id: int, sessao: SessaoDependente) -> FileResponse:
    """O arquivo original, para a tela mostrar ao lado dos campos.

    O caminho vem do banco e aponta para fora do repositório — documento real
    nunca é versionado. Se o arquivo saiu do lugar, o 404 diz isso em vez de
    devolver um PDF de outro documento.
    """
    decisao = _decisao_completa(sessao, decisao_id)
    caminho = Path(decisao.documento.arquivo)

    if not caminho.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"o arquivo de origem não está mais em {caminho}. O banco guarda "
                f"o caminho e o hash, não o conteúdo do documento."
            ),
        )

    # `inline`, e não o `attachment` que o FastAPI usa por padrão quando recebe
    # `filename`. A diferença não aparece em `curl` — os dois devolvem 200 com o
    # PDF certo —, mas `attachment` manda o navegador **baixar** o arquivo, e um
    # `<iframe>` apontado para ele fica em branco. Este endpoint existe para ser
    # exibido ao lado dos campos; o nome continua indo junto, para o caso de
    # alguém de fato baixar.
    return FileResponse(
        caminho,
        media_type="application/pdf",
        filename=caminho.name,
        content_disposition_type="inline",
    )


@roteador.post(
    "/{decisao_id}/correcoes",
    response_model=RespostaDeCorrecao,
    status_code=status.HTTP_201_CREATED,
)
def submete_correcoes(
    decisao_id: int, pedido: PedidoDeCorrecao, sessao: SessaoDependente
) -> RespostaDeCorrecao:
    """Grava as correções do revisor e, por padrão, fecha o item.

    Em lote e numa transação só: metade das correções gravadas com o item
    fechado seria pior que nenhuma, porque o resto se perderia sem alarme.

    Corrigir o mesmo campo de novo **sobrescreve** a correção anterior em vez de
    duplicá-la — a unicidade `(decisao, campo)` existe justamente para não ficar
    ambíguo qual valor vale.
    """
    decisao = _decisao_completa(sessao, decisao_id)

    ja_gravadas = {c.campo: c for c in decisao.documento.correcoes if c.decisao_id == decisao.id}
    campos_pedidos = [c.campo for c in pedido.correcoes]
    if len(set(campos_pedidos)) != len(campos_pedidos):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="o mesmo campo aparece duas vezes no pedido; qual valor vale?",
        )

    for pedida in pedido.correcoes:
        existente = ja_gravadas.get(pedida.campo)
        if existente is not None:
            existente.valor_corrigido = pedida.valor_corrigido
            existente.revisor = pedido.revisor
            existente.corrigido_em = agora()
            continue
        sessao.add(
            Correcao(
                documento_id=decisao.documento_id,
                decisao_id=decisao.id,
                campo=pedida.campo,
                valor_anterior=pedida.valor_anterior,
                valor_corrigido=pedida.valor_corrigido,
                revisor=pedido.revisor,
            )
        )

    if pedido.encerra_revisao:
        decisao.revisada_em = agora()

    sessao.flush()
    return RespostaDeCorrecao(
        decisao_id=decisao.id,
        gravadas=len(pedido.correcoes),
        revisada_em=decisao.revisada_em,
    )
