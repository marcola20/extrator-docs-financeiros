"""Persistência da fila de revisão. Opcional por construção.

O pipeline roda sem banco, e continua rodando: `eval.py` processa 56 documentos
sem abrir conexão nenhuma, e é assim que tem de ser — fazer a medição depender
de um Poststgres de pé transformaria "rodar o eval" numa tarefa de
infraestrutura.

Persistir é escolha, ligada por `PERSISTENCIA_ATIVA`. Desligada, `sessao()`
não existe e quem chamar recebe um erro que diz qual variável ligar, em vez de
uma exceção de conexão recusada a três camadas de distância.
"""

from app.persistencia.modelos import (
    Achado,
    Base,
    Correcao,
    Decisao,
    Documento,
    EstadoDoSinal,
    Extracao,
    Rota,
    Sinal,
    TipoDeDocumento,
)
from app.persistencia.sessao import (
    PersistenciaDesligada,
    cria_engine,
    cria_fabrica_de_sessao,
    sessao,
)

__all__ = [
    "Achado",
    "Base",
    "Correcao",
    "Decisao",
    "Documento",
    "EstadoDoSinal",
    "Extracao",
    "PersistenciaDesligada",
    "Rota",
    "Sinal",
    "TipoDeDocumento",
    "cria_engine",
    "cria_fabrica_de_sessao",
    "sessao",
]
