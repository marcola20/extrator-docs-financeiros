/**
 * Achata o payload da extração em campos editáveis.
 *
 * O boleto é plano — dez campos, dez linhas. O informe é uma árvore, e o
 * endereço de uma linha (`rendimentos_isentos[LCI].valor`) é a mesma forma que
 * o `escopo` dos sinais e o `campo` de uma correção usam. Achatar aqui é o que
 * permite a tela editar os dois documentos com um formulário só, e é o que faz
 * "onde olhar" apontar para uma caixa de texto de verdade.
 *
 * Isto não é lógica de decisão: é transporte de forma. Nada aqui julga valor.
 */

export interface CampoEditavel {
  /** O endereço, no formato que a API espera de volta em `campo`. */
  caminho: string;
  valor: string;
  /** Só para agrupar na tela: `rendimentos_isentos`, ou vazio para escalares. */
  grupo: string;
}

function ehObjeto(valor: unknown): valor is Record<string, unknown> {
  return typeof valor === "object" && valor !== null && !Array.isArray(valor);
}

export function achata(payload: Record<string, unknown>): CampoEditavel[] {
  const campos: CampoEditavel[] = [];

  const percorre = (valor: unknown, caminho: string, grupo: string): void => {
    if (Array.isArray(valor)) {
      for (const [indice, item] of valor.entries()) {
        // A chave da linha é o que o resto do projeto usa como endereço: a
        // especificação da conta, ou o número da linha no formulário. Índice é
        // o último recurso, porque ele muda quando o modelo devolve outra ordem.
        const chave = ehObjeto(item)
          ? String(item.identificador ?? item.especificacao ?? indice)
          : String(indice);
        percorre(item, `${caminho}[${chave}]`, caminho);
      }
      return;
    }
    if (ehObjeto(valor)) {
      for (const [chave, dentro] of Object.entries(valor)) {
        percorre(dentro, caminho ? `${caminho}.${chave}` : chave, caminho || grupo);
      }
      return;
    }
    campos.push({
      caminho,
      valor: valor === null || valor === undefined ? "" : String(valor),
      grupo,
    });
  };

  percorre(payload, "", "");
  return campos;
}

export function agrupa(campos: CampoEditavel[]): Map<string, CampoEditavel[]> {
  const grupos = new Map<string, CampoEditavel[]>();
  for (const campo of campos) {
    const atual = grupos.get(campo.grupo);
    if (atual) atual.push(campo);
    else grupos.set(campo.grupo, [campo]);
  }
  return grupos;
}

/** O último segmento do endereço, para o rótulo não repetir o grupo inteiro. */
export function rotuloDe(caminho: string): string {
  const partes = caminho.split(".");
  return (partes[partes.length - 1] ?? caminho).replaceAll("_", " ");
}
