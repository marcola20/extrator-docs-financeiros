"""Exporta as revisões fechadas como casos de eval.

Comando à parte, e não gatilho no endpoint de correção: exportar escreve fora
do banco, num diretório que pode não existir, e falhar nisso não pode derrubar
o commit de uma correção que o revisor acabou de fazer.

Uso:
    uv run python -m app.avaliacao.exporta_realimentacao
    uv run python -m app.avaliacao.exporta_realimentacao --saida /outro/lugar
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.avaliacao.realimentacao import (
    DIRETORIO_PADRAO,
    CasoDeRealimentacao,
    com_par,
    monta,
    pareia,
)
from app.persistencia.modelos import Correcao, Decisao


def casos_revisados(sessao: Session) -> list[CasoDeRealimentacao]:
    """As decisões que um humano fechou, como casos de eval.

    Só as fechadas. Uma revisão em andamento tem correções parciais, e exportar
    um gabarito pela metade seria pior que não exportar: ele entraria na medição
    afirmando campos que ninguém conferiu.
    """
    decisoes = sessao.scalars(
        select(Decisao)
        .where(Decisao.revisada_em.is_not(None))
        .options(selectinload(Decisao.documento), selectinload(Decisao.extracao))
        .order_by(Decisao.id)
    ).all()

    casos = []
    for decisao in decisoes:
        if decisao.extracao is None:
            # Documento barrado antes do modelo não tem o que realimentar: não
            # há leitura para comparar com a correção.
            continue

        correcoes = {
            c.campo: c.valor_corrigido
            for c in sessao.scalars(select(Correcao).where(Correcao.decisao_id == decisao.id)).all()
        }
        casos.append(
            monta(
                arquivo_pdf=Path(decisao.documento.arquivo),
                tipo=decisao.documento.tipo.value,
                hash_sha256=decisao.documento.hash_sha256,
                payload=dict(decisao.extracao.payload),
                correcoes=correcoes,
                decisao_id=decisao.id,
                revisor=next(
                    (
                        c.revisor
                        for c in sessao.scalars(
                            select(Correcao).where(Correcao.decisao_id == decisao.id)
                        ).all()
                        if c.revisor
                    ),
                    "",
                ),
            )
        )
    return casos


def _analisa(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.avaliacao.exporta_realimentacao",
        description=(
            "Exporta revisões fechadas como casos de eval. O diretório de saída "
            "fica fora do git: os casos referenciam documento real."
        ),
    )
    parser.add_argument("--saida", type=Path, default=DIRETORIO_PADRAO)
    parser.add_argument(
        "--simular",
        action="store_true",
        help="lista o que seria exportado, sem escrever arquivo nenhum",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    from app.avaliacao.realimentacao import grava
    from app.persistencia.sessao import PersistenciaDesligada
    from app.persistencia.sessao import sessao as abre_sessao

    argumentos = _analisa(argv)

    try:
        with abre_sessao() as sessao:
            casos = casos_revisados(sessao)
    except PersistenciaDesligada as erro:
        print(f"\n{erro}", file=sys.stderr)
        return 1

    if not casos:
        print("nenhuma revisão fechada para exportar")
        return 0

    if argumentos.simular:
        for caso in casos:
            print(
                f"  {caso.tipo:8} {caso.procedencia.documento_de_origem:40} "
                f"{len(caso.procedencia.campos_corrigidos)} campo(s) corrigido(s)"
            )
        print(f"\n{len(casos)} caso(s) seriam exportados para {argumentos.saida}")
        return 0

    # Os informes saem apontando um para o outro. O par é descoberto pelo mesmo
    # critério que o domínio usa para decidir se dois informes são comparáveis
    # — mesmo titular, mesma fonte, anos consecutivos —, e sem ele um caso de
    # informe entraria no eval já sem cobertura de cruzamento.
    pareados = {
        id(caso): caso for anterior, atual in pareia(casos) for caso in com_par(anterior, atual)
    }
    por_arquivo = {c.arquivo_pdf: c for c in pareados.values()}
    finais = [por_arquivo.get(caso.arquivo_pdf, caso) for caso in casos]

    for caso in finais:
        grava(caso, argumentos.saida)

    informes = [c for c in finais if c.tipo == "informe"]
    sem_par = [c for c in informes if c.arquivo_do_par is None]
    if sem_par:
        print(
            f"{len(sem_par)} informe(s) sem par de ano consecutivo. Eles não entram "
            f"no eval — o cruzamento entre anos precisa dos dois documentos — e "
            f"passam a entrar quando o par for revisado."
        )

    casos = finais
    tipos = {caso.tipo for caso in casos}
    print(f"{len(casos)} caso(s) em {argumentos.saida} ({', '.join(sorted(tipos))})")
    print(
        "Estes arquivos referenciam documento real e NÃO são versionados. "
        "O eval só os inclui com --com-realimentacao."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
