/**
 * O contrato da API da Fase 4.1, transcrito.
 *
 * Escrito à mão, e não gerado do OpenAPI, por uma razão de tamanho: são doze
 * tipos, e um gerador traria uma dependência de build e um passo a mais para
 * manter. Se o contrato crescer, gerar passa a valer.
 *
 * Nada aqui decide nada. O front não recalcula sinal, não infere estado e não
 * sabe o que faz um documento entrar na fila — isso tudo já foi decidido pelo
 * pipeline e a API transporta. O que este arquivo faz é buscar e tipar.
 */

export type TipoDeDocumento = "boleto" | "informe";
export type Rota = "auto_aprovado" | "revisao_humana";

/**
 * Os **quatro** estados de um sinal.
 *
 * O enunciado desta fase falava em três — conferido, divergente e sem
 * cobertura —, que são os da conferência de quadro da Fase 2. A tabela de
 * sinais da 4.1 tem um quarto: `dispensado`, quando o operador desligou o
 * sinal por configuração. Ele não bloqueia, mas também **não rodou**, e
 * desenhar a interface só para três faria o quarto cair no visual de
 * "conferido" — que é exatamente o erro que esta fase existe para não cometer.
 */
export type EstadoDoSinal = "conferido" | "divergente" | "sem_cobertura" | "dispensado";

export interface SinalNaResposta {
  nome: string;
  estado: EstadoDoSinal;
  /** Vem da API, calculado pela política. O front nunca deriva isto. */
  bloqueia: boolean;
  detalhe: string;
  escopo: string | null;
}

export interface Caixa {
  x0: string | null;
  topo: string | null;
  x1: string | null;
  base: string | null;
}

export interface AchadoNaResposta {
  tipo: string;
  severidade: string;
  trecho: string;
  detalhe: string;
  pagina: number;
  caixa: Caixa;
}

export interface ExtracaoNaResposta {
  payload: Record<string, unknown>;
  prompt: string;
  provedor: string;
  modelo: string;
  tokens_entrada: number;
  tokens_saida: number;
  custo_usd: string;
  latencia_s: string;
  do_cache: boolean;
  erro_de_dominio: string | null;
}

export interface CorrecaoNaResposta {
  campo: string;
  valor_anterior: string;
  valor_corrigido: string;
  revisor: string;
  corrigido_em: string;
}

export interface Diagnostico {
  decisao_id: number;
  documento_id: number;
  arquivo: string;
  hash_sha256: string;
  tipo: TipoDeDocumento;
  rota: Rota;
  ingerido_em: string;
  criada_em: string;
  revisada_em: string | null;
  extracao: ExtracaoNaResposta | null;
  sinais: SinalNaResposta[];
  achados: AchadoNaResposta[];
  correcoes: CorrecaoNaResposta[];
}

export interface ItemDaFila {
  decisao_id: number;
  documento_id: number;
  arquivo: string;
  tipo: TipoDeDocumento;
  rota: Rota;
  criada_em: string;
  revisada_em: string | null;
  sinais_que_bloqueiam: string[];
  /** Subconjunto de `sinais_que_bloqueiam`: os que não tiveram o que conferir. */
  sem_cobertura: string[];
  achados: number;
}

export interface Pagina {
  itens: ItemDaFila[];
  total: number;
  deslocamento: number;
  limite: number;
}

export interface EstatisticasDaFila {
  total: number;
  pendentes: number;
  revisados: number;
  auto_aprovados: number;
  por_tipo: Record<string, number>;
  por_sinal_que_bloqueia: Record<string, number>;
  bloqueados_so_por_falta_de_cobertura: number;
  correcoes: number;
  campos_mais_corrigidos: Record<string, number>;
  custo_total_usd: string;
}

export class ApiIndisponivel extends Error {
  constructor(readonly status: number, readonly detalhe: string) {
    super(detalhe);
  }
}

/** Onde a API está para o **servidor**. O navegador sempre usa `/api`. */
const BASE = process.env.API_INTERNA ?? "http://127.0.0.1:8000";

async function busca<T>(caminho: string): Promise<T> {
  let resposta: Response;
  try {
    resposta = await fetch(`${BASE}${caminho}`, { cache: "no-store" });
  } catch {
    throw new ApiIndisponivel(
      0,
      `A API não respondeu em ${BASE}. Suba-a com "uv run uvicorn app.main:app" ` +
        `ou "docker compose --profile revisao up".`,
    );
  }
  if (!resposta.ok) {
    const corpo = (await resposta.json().catch(() => null)) as { detail?: string } | null;
    throw new ApiIndisponivel(resposta.status, corpo?.detail ?? resposta.statusText);
  }
  return (await resposta.json()) as T;
}

export interface FiltrosDaFila {
  tipo?: TipoDeDocumento;
  sinal?: string;
  estado?: EstadoDoSinal;
  pendentes?: boolean;
}

export function paraConsulta(filtros: FiltrosDaFila): string {
  const parametros = new URLSearchParams();
  if (filtros.tipo) parametros.set("tipo", filtros.tipo);
  if (filtros.sinal) parametros.set("sinal", filtros.sinal);
  if (filtros.estado) parametros.set("estado", filtros.estado);
  if (filtros.pendentes === false) parametros.set("pendentes", "false");
  const texto = parametros.toString();
  return texto ? `?${texto}` : "";
}

export const buscaFila = (filtros: FiltrosDaFila = {}) =>
  busca<Pagina>(`/revisao/fila${paraConsulta(filtros)}`);

export const buscaEstatisticas = () => busca<EstatisticasDaFila>("/revisao/estatisticas");

export const buscaDiagnostico = (id: number) => busca<Diagnostico>(`/revisao/${id}`);
