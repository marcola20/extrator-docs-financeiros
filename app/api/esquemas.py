"""O que a API devolve. É o contrato que a tela da Fase 4 vai consumir.

## O diagnóstico é o produto, não os campos extraídos

Uma tela de revisão que mostrasse só "documento X, campos Y, aprove ou corrija"
seria um CRUD, e jogaria fora tudo que as três fases anteriores construíram. O
que o revisor precisa saber é **por que este documento está na fila**, e o
pipeline já sabe responder isso com precisão:

- qual sinal reprovou, e qual apenas não teve o que conferir — são situações
  diferentes e pedem trabalho diferente do revisor;
- a mensagem que o sinal escreveu, que aponta a causa ("não fecha: CNPJ da
  fonte pagadora inválido", "nenhum quadro tinha total impresso para conferir");
- onde olhar, quando o sinal fala de um lugar específico do documento;
- os trechos que o sanitizador achou, **com a página e as coordenadas**, para
  o revisor comparar com o que está impresso.

Nada disso é calculado aqui. Tudo já foi decidido pelo pipeline e gravado; a
API transporta.

## Os quatro estados atravessam a fronteira

`EstadoDoSinal` sai como está, com os quatro valores. Reduzir a booleano na
serialização desfaria, na última camada, o cuidado que o resto do projeto
carrega desde a Fase 1.2 — e desfaria em silêncio, porque uma resposta JSON com
`"aprovado": false` parece perfeitamente razoável até alguém perguntar se o
sinal chegou a rodar.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.persistencia.modelos import EstadoDoSinal, Rota, TipoDeDocumento


class Caixa(BaseModel):
    """Onde o trecho está na página, para a tela desenhar o retângulo."""

    x0: Decimal | None = None
    topo: Decimal | None = None
    x1: Decimal | None = None
    base: Decimal | None = None

    @property
    def localizada(self) -> bool:
        return self.x0 is not None and self.topo is not None


class AchadoNaResposta(BaseModel):
    """Um trecho suspeito, com o que o sanitizador viu e onde."""

    model_config = ConfigDict(from_attributes=True)

    tipo: str
    severidade: str
    trecho: str
    detalhe: str
    pagina: int
    caixa: Caixa


class SinalNaResposta(BaseModel):
    """O veredito de um sinal, com os quatro estados preservados."""

    model_config = ConfigDict(from_attributes=True)

    nome: str
    estado: EstadoDoSinal
    bloqueia: bool
    detalhe: str
    escopo: str | None = None

    @classmethod
    def de_linha(cls, linha: object) -> "SinalNaResposta":
        estado: EstadoDoSinal = linha.estado  # type: ignore[attr-defined]
        return cls(
            nome=linha.nome,  # type: ignore[attr-defined]
            estado=estado,
            bloqueia=estado.bloqueia,
            detalhe=linha.detalhe,  # type: ignore[attr-defined]
            escopo=linha.escopo,  # type: ignore[attr-defined]
        )


class CorrecaoNaResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    campo: str
    valor_anterior: str
    valor_corrigido: str
    revisor: str
    corrigido_em: datetime


class ItemDaFila(BaseModel):
    """Uma linha da lista. O suficiente para o revisor escolher o que abrir.

    `sinais_que_bloqueiam` vem junto de propósito: sem ele a tela precisaria de
    uma requisição por item para dizer por que cada documento está ali, e a
    lista viraria N+1 chamadas.
    """

    decisao_id: int
    documento_id: int
    arquivo: str
    tipo: TipoDeDocumento
    rota: Rota
    criada_em: datetime
    revisada_em: datetime | None
    sinais_que_bloqueiam: list[str]
    sem_cobertura: list[str]
    """Sinais que bloquearam por não ter tido o que conferir.

    Separado de `sinais_que_bloqueiam` porque o trabalho é outro: um documento
    que falhou numa conferência tem um erro a investigar; um que ninguém
    conseguiu conferir tem uma leitura a fazer do zero."""

    achados: int


class Pagina(BaseModel):
    """Uma fatia da fila, com o total para a tela paginar."""

    itens: list[ItemDaFila]
    total: int
    deslocamento: int
    limite: int


class ExtracaoNaResposta(BaseModel):
    """O que o modelo devolveu, e o que a chamada custou."""

    model_config = ConfigDict(from_attributes=True)

    payload: dict[str, object]
    """O bruto, como o modelo escreveu. É o que a tela mostra para corrigir."""

    prompt: str
    provedor: str
    modelo: str
    tokens_entrada: int
    tokens_saida: int
    custo_usd: Decimal
    latencia_s: Decimal
    do_cache: bool
    erro_de_dominio: str | None


class Diagnostico(BaseModel):
    """Tudo que o pipeline sabe sobre um documento da fila.

    É a resposta que a tela abre. Ver a nota do módulo sobre por que ela é
    maior que "os campos extraídos".
    """

    decisao_id: int
    documento_id: int
    arquivo: str
    hash_sha256: str
    tipo: TipoDeDocumento
    rota: Rota
    ingerido_em: datetime
    criada_em: datetime
    revisada_em: datetime | None

    extracao: ExtracaoNaResposta | None
    """Nulo quando o documento foi barrado antes de chegar ao modelo."""

    sinais: list[SinalNaResposta]
    achados: list[AchadoNaResposta]
    correcoes: list[CorrecaoNaResposta]

    @property
    def bloqueadores(self) -> list[SinalNaResposta]:
        return [s for s in self.sinais if s.bloqueia]


class CorrecaoPedida(BaseModel):
    """Um campo que o revisor corrigiu."""

    campo: str = Field(min_length=1, max_length=200)
    valor_corrigido: str = Field(max_length=2000)
    valor_anterior: str = Field(default="", max_length=2000)


class PedidoDeCorrecao(BaseModel):
    """Um ou mais campos, de uma vez.

    Em lote porque o revisor corrige a tela inteira e clica uma vez: mandar um
    pedido por campo faria metade das correções sobreviverem a uma falha no
    meio, e a decisão ficaria fechada com o resto perdido.
    """

    correcoes: list[CorrecaoPedida] = Field(min_length=1, max_length=200)
    revisor: str = Field(default="", max_length=120)
    encerra_revisao: bool = True
    """Marca a decisão como revisada. Falso permite salvar sem fechar o item."""


class RespostaDeCorrecao(BaseModel):
    decisao_id: int
    gravadas: int
    revisada_em: datetime | None


class EstatisticasDaFila(BaseModel):
    """Números da fila. O que uma tela de acompanhamento mostra no topo.

    `bloqueados_so_por_falta_de_cobertura` aparece separado pela mesma razão do
    relatório de eval (ADR 009): somá-lo com o resto faria a fila parecer cheia
    de documentos com erro, quando parte dela é de documentos que ninguém
    conseguiu conferir. São filas de trabalho diferentes.
    """

    total: int
    pendentes: int
    revisados: int
    auto_aprovados: int
    por_tipo: dict[str, int]
    por_sinal_que_bloqueia: dict[str, int]
    bloqueados_so_por_falta_de_cobertura: int
    correcoes: int
    campos_mais_corrigidos: dict[str, int]
    custo_total_usd: Decimal
