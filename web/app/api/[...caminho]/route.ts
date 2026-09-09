/**
 * O proxy para a API, em runtime.
 *
 * Isto começou como um `rewrites()` no `next.config.ts`, e não funcionava na
 * imagem: o Next **avalia os rewrites durante o build** e grava o destino já
 * resolvido no manifesto de rotas. Com `API_INTERNA` ausente na hora de
 * construir, o que ficou congelado foi o padrão `127.0.0.1:8000` — que dentro do
 * contêiner do front não é a API, é ele mesmo. O sintoma foi um 500 só no PDF,
 * porque as páginas leem a variável em tempo de requisição e o rewrite não.
 *
 * Um route handler lê o ambiente a cada chamada, então a mesma imagem serve
 * para `docker compose` (onde a API é `http://api:8000`) e para o
 * desenvolvimento local (onde ela é `127.0.0.1:8000`).
 *
 * O corpo da resposta é repassado como veio: o PDF é binário e não pode passar
 * por serialização.
 */

const API = () => process.env.API_INTERNA ?? "http://127.0.0.1:8000";

/**
 * O mesmo tempo limite do cliente das páginas (`lib/api.ts`), e pelo mesmo
 * motivo: na hospedagem gratuita a API dorme, e o `fetch` sem limite deixaria o
 * `<iframe>` do PDF girando para sempre em vez de dizer o que houve.
 */
const ESPERA_MS = Number(process.env.API_ESPERA_MS ?? 65_000);

async function encaminha(requisicao: Request, caminho: string[]): Promise<Response> {
  const consulta = new URL(requisicao.url).search;
  const destino = `${API()}/${caminho.join("/")}${consulta}`;

  let resposta: Response;
  try {
    resposta = await fetch(destino, {
      method: requisicao.method,
      headers: requisicao.headers.get("content-type")
        ? { "content-type": requisicao.headers.get("content-type")! }
        : undefined,
      body: requisicao.method === "GET" ? undefined : await requisicao.text(),
      cache: "no-store",
      signal: AbortSignal.timeout(ESPERA_MS),
    });
  } catch (falha) {
    const expirou = falha instanceof Error && falha.name === "TimeoutError";
    return Response.json(
      {
        detail: expirou
          ? `A API não respondeu em ${Math.round(ESPERA_MS / 1000)}s. Se esta é a ` +
            `demonstração pública, o servidor está acordando: tente de novo.`
          : `A API não respondeu em ${API()}.`,
      },
      // 504 quando o tempo esgotou, 502 quando a conexão foi recusada. São
      // situações diferentes — "está subindo" e "não está lá" —, e o status é
      // onde essa diferença chega a quem depura pelo painel de rede.
      { status: expirou ? 504 : 502 },
    );
  }

  // `cache-control` faz parte da lista, e a ausência dele custou caro: a API
  // passou a mandar `no-store` para o navegador parar de reusar uma resposta
  // antiga, o proxy descartou o cabeçalho no caminho, e a correção não chegou a
  // lugar nenhum. Um proxy que filtra cabeçalhos precisa filtrar por uma razão
  // dita — estes quatro são o que o navegador usa para exibir e para decidir se
  // pode reaproveitar.
  const cabecalhos = new Headers();
  for (const nome of [
    "content-type",
    "content-disposition",
    "content-length",
    "cache-control",
  ]) {
    const valor = resposta.headers.get(nome);
    if (valor) cabecalhos.set(nome, valor);
  }
  return new Response(resposta.body, { status: resposta.status, headers: cabecalhos });
}

export async function GET(
  requisicao: Request,
  { params }: { params: Promise<{ caminho: string[] }> },
) {
  return encaminha(requisicao, (await params).caminho);
}

export async function POST(
  requisicao: Request,
  { params }: { params: Promise<{ caminho: string[] }> },
) {
  return encaminha(requisicao, (await params).caminho);
}
