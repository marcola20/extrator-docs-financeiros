/**
 * A codificação visual dos quatro estados. É o arquivo mais importante do front.
 *
 * O projeto inteiro se apoia numa distinção que uma interface descuidada apaga
 * em silêncio: **um sinal que não teve o que conferir não é um sinal que
 * aprovou.** No banco isso é `SEM_COBERTURA` e não `false`; na API atravessa
 * como os quatro valores; e aqui ele precisa **parecer** diferente de aprovado.
 *
 * Duas regras de desenho carregam isso:
 *
 * 1. **Só `conferido` recebe marca de certo.** Os outros três recebem glifos
 *    que não podem ser lidos como aprovação — `!` para divergente, `—` para
 *    quem não teve o que conferir, `⦸` para quem foi desligado. Um ✓ cinza
 *    ainda é um ✓, e num relance é o que a pessoa lê.
 *
 * 2. **`sem_cobertura` tem borda tracejada.** Preenchimento contínuo é a
 *    linguagem de "resolvido"; o tracejado diz "aqui falta coisa" sem depender
 *    de cor, o que também resolve daltonismo — vermelho e verde deixam de ser
 *    a única diferença entre reprovado e aprovado.
 *
 * O rótulo nunca é uma palavra só. "Sem cobertura" não significa nada para quem
 * abre a tela pela primeira vez; "não havia o que conferir" significa.
 */

import type { EstadoDoSinal } from "./api";

export interface Aparencia {
  /** O que aparece no chip. Curto, mas não abreviado a ponto de virar jargão. */
  rotulo: string;
  /** A frase que explica o estado a quem nunca viu esta tela. */
  explicacao: string;
  glifo: string;
  classes: string;
  /** Ordem de leitura: o que exige trabalho primeiro. */
  peso: number;
}

export const APARENCIA: Record<EstadoDoSinal, Aparencia> = {
  divergente: {
    rotulo: "divergente",
    explicacao: "o sinal rodou e reprovou",
    glifo: "!",
    classes: "border-rose-300 bg-rose-50 text-rose-900",
    peso: 0,
  },
  sem_cobertura: {
    rotulo: "sem cobertura",
    explicacao: "não havia o que conferir — não é aprovação",
    glifo: "—",
    // Tracejado de propósito: ver a regra 2 no topo do arquivo.
    classes: "border-dashed border-amber-400 bg-amber-50/60 text-amber-900",
    peso: 1,
  },
  dispensado: {
    rotulo: "dispensado",
    explicacao: "desligado por configuração; o ponto cego é escolhido",
    glifo: "⦸",
    classes: "border-dashed border-slate-300 bg-slate-50 text-slate-600",
    peso: 2,
  },
  conferido: {
    rotulo: "conferido",
    explicacao: "o sinal rodou e aprovou",
    glifo: "✓",
    classes: "border-emerald-300 bg-emerald-50 text-emerald-900",
    peso: 3,
  },
};

/**
 * O que cada sinal verifica, em uma frase.
 *
 * A API manda o nome (`aritmetica`) e a mensagem do caso concreto ("nenhum
 * quadro tinha total impresso"). Falta a pergunta que o sinal faz, e sem ela o
 * nome é jargão. Isto é texto de interface — não é regra, e não decide nada.
 */
export const O_QUE_O_SINAL_VERIFICA: Record<string, string> = {
  sanitizacao: "procura texto escondido ou instrução dirigida ao modelo dentro do documento",
  digito_verificador: "cruza banco, valor e vencimento com os dígitos da linha digitável",
  dominio: "confere os DVs de CNPJ e CPF, o exercício, e a soma de cada quadro",
  aritmetica: "soma as linhas de cada quadro e compara com o total impresso",
  cruzamento: "compara o saldo de 31/12 com o que o informe do ano anterior declara",
  grounding: "pergunta se cada valor extraído aparece mesmo no texto da página",
  consistencia: "compara duas leituras independentes do mesmo documento",
  campo_a_revisar: "lugar apontado por outro sinal para o revisor conferir",
};

export function aparenciaDe(estado: EstadoDoSinal): Aparencia {
  return APARENCIA[estado];
}

/** Bloqueadores primeiro, e entre eles o que reprovou antes do que não rodou. */
export function ordenaParaLeitura<T extends { estado: EstadoDoSinal; nome: string }>(
  sinais: readonly T[],
): T[] {
  return [...sinais].sort(
    (a, b) => APARENCIA[a.estado].peso - APARENCIA[b.estado].peso || a.nome.localeCompare(b.nome),
  );
}

export function nomeLegivel(nome: string): string {
  return nome.replaceAll("_", " ");
}
