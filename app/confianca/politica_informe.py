"""Roteamento do informe: seis sinais, e a regra que separa cobertura de aprovação.

Função pura, como a do boleto: recebe os sinais já calculados e devolve a rota
com a razão escrita. Não chama modelo, não abre arquivo.

## Os seis, na ordem de força da evidência

1. **Sanitização** — achado nunca auto-aprova (política da Fase 1.2).
2. **Cruzamento entre anos** — dois documentos emitidos em momentos diferentes
   afirmando a mesma grandeza. É o único sinal do projeto que um adversário
   com controle da página não satisfaz sozinho (ADR 007).
3. **Domínio** — DV do CNPJ e do CPF, exercício igual ao ano mais um, e a soma
   de cada quadro contra o total que o próprio quadro imprime (ADR 002, 007).
4. **Aritmética de quadro** — a mesma soma, mas reportada quadro a quadro e
   **calculada sobre o que o modelo escreveu**, para continuar falando quando
   o domínio recusa a instância inteira.
5. **Grounding** — pega invenção, não pega troca de campo.
6. **Auto-consistência** — divergência é evidência forte; concordância, fraca.

Qualquer um que reprove manda o documento para revisão. É a mesma escolha do
ADR 002 e da Fase 1.2: falso positivo custa tempo de revisor, falso negativo
custa um erro em declaração de imposto, e os dois não se equivalem.

## Não ter o que conferir não é aprovação

É a regra que este módulo existe para não deixar escapar, e ela vem de dois
lugares que já a tinham escrito:

- a Fase 1.2 decidiu que um PDF **sem camada de texto** vai para revisão. Os
  detectores rodaram, não acharam nada, e "não achou" não é "está limpo" — é
  "não inspecionou";
- a Fase 2.1 decidiu que um quadro **sem total impresso** sai como `SEM_TOTAL`,
  e que aprovar por omissão faria todo quadro do comprovante parecer conferido.

Aqui as duas viram a mesma regra: **um sinal que não teve o que conferir conta
como não executado, e não executado bloqueia** (`Veredito.bloqueia`). Na
prática:

- informe cujos três quadros são `SEM_TOTAL` → a aritmética não rodou;
- par sem conta em comum, ou par incomparável, ou documento sem par extraído →
  o cruzamento não rodou.

**A consequência é grande e é o ponto:** nenhum comprovante de fonte pagadora
é auto-aprovável, porque ele não tem total e não tem saldo. Não é um defeito
da política — é o documento que não oferece verificação, e o ADR 007 já
antecipava que a política teria de mandar à revisão o que o layout não cobre.
O relatório do eval separa as duas contagens (auto-aprovados com cobertura
real, e bloqueados só por falta dela), porque somá-las é o que faria uma taxa
de auto-aprovação descrever duas coisas diferentes.
"""

from app.confianca.consistencia import ResultadoConsistencia
from app.confianca.grounding import ResultadoGrounding
from app.confianca.politica import DecisaoFinal, Rota, Sinal, Veredito
from app.dominio.cruzamento import ResultadoCruzamento
from app.extracao.extrator_informe import ExtracaoDeInforme
from app.seguranca.politica import Decisao as DecisaoDeSanitizacao

SEM_PAR = "o documento não tem par de ano consecutivo extraído; nada foi cruzado"


def _veredito_do_cruzamento(
    cruzamento: ResultadoCruzamento | None, motivo_de_nao_rodar: str
) -> Veredito:
    """O sinal mais forte da fase, e o que mais precisa distinguir cobertura.

    Três situações que a leitura descuidada junta, e que aqui saem separadas:

    - **não rodou** — não havia par extraído. Não executou;
    - **rodou e não pôde afirmar nada** — par incomparável (outro titular,
      outra fonte, anos não consecutivos), ou comparável e sem conta em comum,
      que é o caso de todo par de comprovantes de fonte pagadora. Também não
      executou: `ResultadoCruzamento.valido` sai `True` num par sem conta
      nenhuma, e tratar isso como aprovação é exatamente o erro;
    - **rodou e afirmou** — houve conta conferida, e aí `valido` significa algo.
    """
    if cruzamento is None:
        return Veredito(
            sinal=Sinal.CRUZAMENTO,
            aprovou=False,
            executou=False,
            detalhe=motivo_de_nao_rodar or SEM_PAR,
        )

    if not cruzamento.tem_cobertura:
        detalhe = (
            f"não conferiu nada: {cruzamento.descricao()}"
            if not cruzamento.comparavel
            else (
                "os dois informes são comparáveis e não têm conta em comum: "
                "nenhum saldo foi cruzado entre os anos"
            )
        )
        return Veredito(sinal=Sinal.CRUZAMENTO, aprovou=False, executou=False, detalhe=detalhe)

    return Veredito(
        sinal=Sinal.CRUZAMENTO,
        aprovou=cruzamento.valido,
        executou=True,
        detalhe=cruzamento.descricao(),
    )


def _veredito_da_aritmetica(extracao: ExtracaoDeInforme) -> Veredito:
    """Quadro sem total não foi conferido, e isso não é aprovação (ADR 007)."""
    return Veredito(
        sinal=Sinal.ARITMETICA,
        aprovou=not extracao.quadros_divergentes,
        executou=extracao.aritmetica_teve_cobertura,
        detalhe=extracao.descricao_da_aritmetica(),
    )


def _campos_a_revisar(
    extracao: ExtracaoDeInforme,
    grounding: ResultadoGrounding,
    consistencia: ResultadoConsistencia,
    cruzamento: ResultadoCruzamento | None,
) -> tuple[str, ...]:
    """Os lugares do documento que o revisor precisa olhar, e não só os campos.

    No informe o endereço é o dado útil: `rendimentos_isentos[LCI].valor` diz
    onde olhar; "valor" não diz nada num documento com quarenta valores.
    """
    lugares = {c.onde for c in grounding.ausentes}
    lugares |= {d.campo for d in consistencia.divergencias}
    lugares |= {c.quadro for c in extracao.quadros_divergentes}
    if cruzamento is not None:
        lugares |= {d.especificacao for d in cruzamento.divergencias}
        lugares |= {c.especificacao for c in cruzamento.contas_novas_com_historico}
    return tuple(sorted(lugares))


def decide(
    *,
    sanitizacao: DecisaoDeSanitizacao,
    extracao: ExtracaoDeInforme,
    grounding: ResultadoGrounding,
    consistencia: ResultadoConsistencia,
    cruzamento: ResultadoCruzamento | None,
    motivo_sem_cruzamento: str = "",
) -> DecisaoFinal:
    """Combina os seis sinais. Pura: nada aqui toca rede ou disco."""
    vereditos = (
        Veredito(
            sinal=Sinal.SANITIZACAO,
            aprovou=sanitizacao.auto_aprovavel,
            executou=True,
            detalhe=sanitizacao.motivo,
        ),
        _veredito_do_cruzamento(cruzamento, motivo_sem_cruzamento),
        Veredito(
            sinal=Sinal.DOMINIO,
            aprovou=extracao.fecha_no_dominio,
            executou=True,
            detalhe=(
                "CNPJ, CPF, exercício e somas dos quadros conferem"
                if extracao.fecha_no_dominio
                else f"não fecha: {extracao.erro_de_dominio}"
            ),
        ),
        _veredito_da_aritmetica(extracao),
        Veredito(
            sinal=Sinal.GROUNDING,
            aprovou=grounding.aprovado,
            executou=True,
            detalhe=grounding.descricao(),
        ),
        Veredito(
            sinal=Sinal.CONSISTENCIA,
            aprovou=consistencia.concordam,
            executou=consistencia.executou,
            detalhe=consistencia.descricao(),
            dispensado=consistencia.dispensado,
        ),
    )

    bloqueado = any(v.bloqueia for v in vereditos)
    return DecisaoFinal(
        rota=Rota.REVISAO_HUMANA if bloqueado else Rota.AUTO_APROVADO,
        vereditos=vereditos,
        campos_a_revisar=_campos_a_revisar(extracao, grounding, consistencia, cruzamento),
    )
