"""A página de entrada da demonstração: os casos, resolvidos para documentos.

`app/demo.py` diz **quais** situações a demonstração apresenta e em qual PDF
cada uma está. Este módulo resolve cada uma para a decisão que o pipeline
gravou sobre aquele PDF, e devolve o desfecho junto — qual sinal bloqueou, se
algum — para a tela desenhar sem concluir nada por conta própria.

## Por que o casamento é pelo caminho

A identidade de um documento é o hash do conteúdo (ver
`app.persistencia.gravacao`), e casar por hash aqui seria mais preciso. Ficou
pelo caminho gravado por uma razão de peso: importar `gravacao` traria
`app.extracao`, e com ela pdfplumber e o SDK do provedor para dentro de um
processo que existe para **não** carregar isso. Um documento por caminho, a
decisão mais recente — e quando o corpus é regerado sem semear de novo, o caso
aparece como indisponível, que é a resposta certa.
"""

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencias import ConfiguracaoDependente, SessaoDependente
from app.api.esquemas import CasoNaEntrada, Entrada
from app.demo import CASOS, Caso
from app.persistencia.modelos import Achado, Decisao, Documento, EstadoDoSinal

roteador = APIRouter(prefix="/demo", tags=["demonstração"])


def _decisao_de(sessao: Session, arquivo: str) -> Decisao | None:
    """A decisão mais recente sobre este caminho, ou nenhuma."""
    return sessao.scalars(
        select(Decisao)
        .join(Documento, Decisao.documento_id == Documento.id)
        .where(Documento.arquivo == arquivo)
        .order_by(Decisao.criada_em.desc(), Decisao.id.desc())
        .limit(1)
        .options(selectinload(Decisao.sinais))
    ).one_or_none()


def _caso(sessao: Session, caso: Caso) -> CasoNaEntrada:
    """Resolve um caso para a decisão gravada sobre o PDF dele."""
    arquivo = caso.arquivo
    decisao = None if arquivo is None else _decisao_de(sessao, str(arquivo))

    if decisao is None:
        return CasoNaEntrada(
            chave=caso.chave,
            titulo=caso.titulo,
            frase=caso.frase,
            arquivo="" if arquivo is None else str(arquivo),
            decisao_id=None,
            rota=None,
            sinais_que_bloqueiam=[],
            sem_cobertura=[],
            achados=0,
        )

    bloqueiam = [s for s in decisao.sinais if s.estado.bloqueia and s.escopo is None]
    return CasoNaEntrada(
        chave=caso.chave,
        titulo=caso.titulo,
        frase=caso.frase,
        arquivo=str(arquivo),
        decisao_id=decisao.id,
        rota=decisao.rota,
        sinais_que_bloqueiam=[s.nome for s in bloqueiam],
        sem_cobertura=[s.nome for s in bloqueiam if s.estado is EstadoDoSinal.SEM_COBERTURA],
        achados=sessao.scalar(
            select(func.count()).select_from(Achado).where(Achado.decisao_id == decisao.id)
        )
        or 0,
    )


@roteador.get("/casos", response_model=Entrada)
def casos(sessao: SessaoDependente, settings: ConfiguracaoDependente) -> Entrada:
    """Os casos da demonstração, na ordem em que a entrada os apresenta."""
    return Entrada(
        somente_leitura=settings.demo_somente_leitura,
        casos=[_caso(sessao, caso) for caso in CASOS],
    )
