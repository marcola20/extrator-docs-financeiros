import Link from "next/link";
import {
  ApiIndisponivel,
  buscaCasos,
  type CasoNaEntrada,
} from "@/lib/api";
import { AvisoDaApi } from "@/componentes/AvisoDaApi";
import { nomeLegivel } from "@/lib/sinais";

/**
 * A porta de entrada: os casos por situação, não por nome de arquivo.
 *
 * ## Por que esta página existe
 *
 * A fila lista documentos, e é a tela certa para quem revisa — a pessoa já sabe
 * o que está fazendo ali. Para quem abre o link pela primeira vez ela é uma
 * lista de nomes como `adversarial-005.pdf`, e nenhum deles diz o que há de
 * interessante dentro.
 *
 * Então a entrada apresenta cinco **situações**, uma frase cada, e o clique leva
 * direto ao diagnóstico daquele documento. Elas foram escolhidas para não se
 * repetirem: dois casos em que um sinal reprovou por motivos opostos, um em que
 * o sanitizador achou o que o revisor não veria, um em que **nada** reprovou e
 * ninguém conseguiu conferir, e um em que deu certo.
 *
 * ## O desfecho de cada caso vem da API
 *
 * Os chips de "reprovou" e "não conferiu" são os mesmos da fila, e pelos mesmos
 * dados: a API manda quais sinais bloquearam e quais não tiveram o que conferir.
 * Esta página não olha sinal para concluir nada — é a regra do ADR 011, e ela
 * vale aqui do mesmo jeito.
 */
export default async function PaginaDeEntrada() {
  let entrada;
  try {
    entrada = await buscaCasos();
  } catch (erro) {
    if (erro instanceof ApiIndisponivel) return <AvisoDaApi erro={erro} />;
    throw erro;
  }

  const disponiveis = entrada.casos.filter((caso) => caso.decisao_id !== null);

  return (
    <div className="space-y-8">
      <header className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">
          Extração de documentos financeiros, com revisão humana onde ela é
          necessária
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-tinta-fraca">
          Um pipeline lê boletos e informes de rendimentos com um modelo de
          linguagem, e depois <strong className="font-medium text-tinta">confere
          a leitura contra o próprio documento</strong> — dígitos verificadores,
          somas, cruzamento entre anos. O que fecha segue sozinho; o que não fecha,
          e o que ninguém conseguiu conferir, vai para uma fila de revisão.
        </p>
        <p className="mt-2 text-sm leading-relaxed text-tinta-fraca">
          Abaixo estão cinco documentos reais do corpus sintético, escolhidos
          porque cada um mostra uma coisa diferente. Clique em qualquer um para
          ver o diagnóstico completo ao lado do PDF.
        </p>
      </header>

      {entrada.somente_leitura && <NotaDeSomenteLeitura />}

      {disponiveis.length === 0 ? (
        <SemCasos />
      ) : (
        <ol className="space-y-3">
          {entrada.casos.map((caso, indice) => (
            <li key={caso.chave}>
              <Caso caso={caso} numero={indice + 1} />
            </li>
          ))}
        </ol>
      )}

      <p className="border-t border-borda pt-5 text-sm text-tinta-fraca">
        Ou veja{" "}
        <Link href="/fila" className="text-tinta underline underline-offset-2">
          a fila de revisão inteira
        </Link>
        , com os filtros por tipo de documento e por sinal que bloqueou.
      </p>
    </div>
  );
}

/**
 * Um caso. Título, a frase da situação, e o que o pipeline decidiu sobre ele.
 *
 * Quando o documento não está no banco o cartão continua na lista, sem link e
 * dizendo por quê. Some-lo seria pior: a numeração mudaria e ninguém saberia
 * que faltou um caso.
 */
function Caso({ caso, numero }: { caso: CasoNaEntrada; numero: number }) {
  const semCobertura = new Set(caso.sem_cobertura);
  const reprovaram = caso.sinais_que_bloqueiam.filter((s) => !semCobertura.has(s));

  const conteudo = (
    <>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-xs text-tinta-fraca">{numero}</span>
        <h2 className="text-base font-semibold tracking-tight">{caso.titulo}</h2>
        {caso.arquivo && (
          <span className="ml-auto font-mono text-[11px] text-tinta-fraca">
            {caso.arquivo.split("/").pop()}
          </span>
        )}
      </div>

      <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-tinta-fraca">
        {caso.frase}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {caso.rota === "auto_aprovado" && (
          <span className="rounded-full border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-xs text-emerald-900">
            <span aria-hidden className="mr-1 font-mono">
              ✓
            </span>
            auto-aprovado
          </span>
        )}
        {reprovaram.map((sinal) => (
          <span
            key={sinal}
            className="rounded-full border border-rose-300 bg-rose-50 px-2 py-0.5 text-xs text-rose-900"
          >
            <span aria-hidden className="mr-1 font-mono">
              !
            </span>
            {nomeLegivel(sinal)} reprovou
          </span>
        ))}
        {caso.sem_cobertura.map((sinal) => (
          <span
            key={sinal}
            className="rounded-full border border-dashed border-amber-400 bg-amber-50/60 px-2 py-0.5 text-xs text-amber-900"
          >
            <span aria-hidden className="mr-1 font-mono">
              —
            </span>
            {nomeLegivel(sinal)} não conferiu
          </span>
        ))}
        {caso.achados > 0 && (
          <span className="rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs text-rose-900">
            {caso.achados} {caso.achados === 1 ? "trecho suspeito" : "trechos suspeitos"}
          </span>
        )}
      </div>
    </>
  );

  if (caso.decisao_id === null) {
    return (
      <div className="rounded-lg border border-dashed border-borda bg-white/50 px-5 py-4 opacity-70">
        {conteudo}
        <p className="mt-2 text-xs text-tinta-fraca">
          Este documento não está no banco desta instância. A fila é povoada por{" "}
          <code className="font-mono">semeia_fila</code>, e ele não passou por lá —
          ou o corpus foi regerado depois.
        </p>
      </div>
    );
  }

  return (
    <Link
      href={`/revisao/${caso.decisao_id}`}
      className="block rounded-lg border border-borda bg-white px-5 py-4 transition-colors hover:border-tinta-fraca"
    >
      {conteudo}
    </Link>
  );
}

/**
 * A nota da demonstração pública.
 *
 * Diz que a gravação está desligada **e** que quem recusa é a API, não a tela.
 * A diferença é o ponto: um front que só escondesse o botão deixaria a rota de
 * escrita aberta, e dizer isso aqui é mais honesto do que deixar a pessoa
 * descobrir que o botão sumiu.
 */
function NotaDeSomenteLeitura() {
  return (
    <div className="rounded-lg border border-sky-200 bg-sky-50/70 px-5 py-4">
      <p className="text-sm font-medium text-sky-900">
        Demonstração pública, somente leitura
      </p>
      <p className="mt-1 max-w-3xl text-sm leading-relaxed text-sky-900/90">
        Dá para abrir qualquer documento, ver o diagnóstico e navegar pela fila. O
        que está desligado é <strong>gravar correção</strong>, para o que um
        visitante digita não aparecer na tela do visitante seguinte — e quem
        recusa é a API, não esta página. Rodando o projeto localmente a revisão
        grava normalmente.
      </p>
    </div>
  );
}

function SemCasos() {
  return (
    <div className="rounded-lg border border-dashed border-borda bg-white/60 px-5 py-8 text-center">
      <p className="text-sm font-medium">Nenhum caso disponível</p>
      <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-tinta-fraca">
        O banco está de pé, mas vazio. Povoe a fila com{" "}
        <code className="font-mono">
          PERSISTENCIA_ATIVA=1 uv run python -m app.geradores.semeia_fila
        </code>
        , que lê o gabarito ao lado de cada PDF e não chama o modelo.
      </p>
    </div>
  );
}
