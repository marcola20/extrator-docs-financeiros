/**
 * Buscar na API tratando "ainda não" como "ainda não".
 *
 * ## O defeito que isto corrige
 *
 * Na demonstração pública são dois serviços gratuitos dormindo, e a primeira
 * visita os acorda **em série**: a hospedagem segura a requisição do navegador
 * até o front subir, e só então o servidor do Next chama a API — que ainda está
 * dormindo, e para essa chamada a hospedagem responde 502. A tela tratava isso
 * como falha definitiva: quem abria o link pela primeira vez via "A API não
 * respondeu — Bad Gateway", e só funcionava para quem tivesse acordado a API
 * antes, abrindo `/health` à mão.
 *
 * O tratamento de cold start que existia cobria o front acordando (`loading.tsx`)
 * e a API que não responde nada (`AvisoDaApi`). Faltava a que responde "ainda não".
 *
 * ## 502, 503 e 504 são "ainda não" — quando não vêm da API
 *
 * É o raciocínio do `ErroTransitorio` no limitador do provedor
 * (`app/llm/limitador.py`): o erro diz "ainda não", não "não", e desistir na
 * primeira vez transforma espera em falha. Então a busca repete, com backoff,
 * até um prazo total.
 *
 * O critério não é só o status, e a razão é que a própria API responde **503**
 * quando a persistência está desligada (`app/api/dependencias.py`). Aquele 503
 * diz "não": nenhuma espera liga o banco, e repeti-lo por um minuto só atrasaria
 * a tela que ensina a ligá-lo. O que separa os dois é quem respondeu — a API
 * responde erro em JSON com `detail`, como todo erro do FastAPI; quem está na
 * frente dela, não.
 *
 * ## Só quem chama sabe se pode repetir
 *
 * Um 504 não garante que o pedido deixou de chegar: a gravação pode ter
 * acontecido e só a resposta ter se perdido. Repetir escrita às cegas é o jeito
 * de gravar duas vezes, então a repetição é uma escolha explícita de quem chama.
 */

/** Os status com que quem está na frente da API diz que ela ainda não está lá. */
const TRANSITORIOS: ReadonlySet<number> = new Set([502, 503, 504]);

/**
 * Quanto esperar, no total, antes de desistir.
 *
 * É o prazo da busca **inteira**, com as repetições dentro, e não o de cada
 * tentativa: quem abre a página sente o total. Generoso de propósito — um valor
 * curto desistiria de um servidor que ia responder —, e finito também de
 * propósito: o padrão do `fetch`, esperar indefinidamente, deixaria a página
 * pendurada sem nunca dizer o que houve.
 */
export const PRAZO_MS = Number(process.env.API_ESPERA_MS ?? 65_000);

/** A primeira espera entre tentativas. Dobra a cada uma, até o teto. */
const ESPERA_INICIAL_MS = 1_000;
const ESPERA_MAXIMA_MS = 8_000;

export interface ResultadoDaBusca {
  resposta: Response;
  tentativas: number;
  decorridoMs: number;
  /**
   * O prazo acabou com a resposta ainda dizendo "ainda não".
   *
   * Separado de `resposta.ok` porque a tela diz coisas diferentes: um 502 que
   * durou o prazo inteiro é o servidor que não acordou, e não um erro que a API
   * devolveu.
   */
  esgotou: boolean;
}

/**
 * Busca `url`, repetindo enquanto a resposta for transitória e houver prazo.
 *
 * Devolve a última resposta. Falha de conexão e estouro do prazo continuam
 * saindo como exceção do `fetch` — `TimeoutError`, no segundo caso —, porque aí
 * não há resposta nenhuma para devolver.
 *
 * A última tentativa não é espremida contra o fim do prazo: quando a espera
 * seguinte não cabe no que sobrou, a busca para ali. O custo é desistir até
 * `ESPERA_MAXIMA_MS` antes do prazo; o ganho é que o fim chega sempre como
 * "esgotou", e não como uma tentativa abortada no meio que viraria `TimeoutError`
 * e contaria outra história.
 */
export async function buscaEsperandoAcordar(
  url: string,
  init: RequestInit,
  { repete }: { repete: boolean },
): Promise<ResultadoDaBusca> {
  const inicio = Date.now();
  const prazo = inicio + PRAZO_MS;
  let espera = ESPERA_INICIAL_MS;

  for (let tentativas = 1; ; tentativas++) {
    const resposta = await fetch(url, {
      ...init,
      signal: AbortSignal.timeout(Math.max(prazo - Date.now(), 1)),
    });
    const decorridoMs = Date.now() - inicio;

    if (!repete || !(await ehTransitoria(resposta))) {
      return { resposta, tentativas, decorridoMs, esgotou: false };
    }
    if (Date.now() + espera >= prazo) {
      return { resposta, tentativas, decorridoMs, esgotou: true };
    }

    // Libera a conexão da resposta descartada antes de dormir.
    await resposta.body?.cancel();
    await dorme(espera);
    espera = Math.min(espera * 2, ESPERA_MAXIMA_MS);
  }
}

async function ehTransitoria(resposta: Response): Promise<boolean> {
  if (!TRANSITORIOS.has(resposta.status)) return false;
  return !(await veioDaApi(resposta));
}

/**
 * A API responde erro como todo FastAPI: JSON com `detail`.
 *
 * Lê de uma cópia, para o corpo continuar inteiro para quem chamou.
 */
async function veioDaApi(resposta: Response): Promise<boolean> {
  const corpo: unknown = await resposta
    .clone()
    .json()
    .catch(() => null);
  return typeof corpo === "object" && corpo !== null && "detail" in corpo;
}

function dorme(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
