import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiIndisponivel, buscaDiagnostico } from "@/lib/api";
import { AreaDeRevisao } from "@/componentes/AreaDeRevisao";
import { AvisoDaApi } from "@/componentes/AvisoDaApi";
import { PainelDeSinais } from "@/componentes/PainelDeSinais";
import { PorQueEstaAqui } from "@/componentes/PorQueEstaAqui";

export default async function PaginaDeRevisao({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const numero = Number(id);
  if (!Number.isInteger(numero)) notFound();

  let diagnostico;
  try {
    diagnostico = await buscaDiagnostico(numero);
  } catch (erro) {
    if (erro instanceof ApiIndisponivel && erro.status === 404) notFound();
    if (erro instanceof ApiIndisponivel) return <AvisoDaApi erro={erro} />;
    throw erro;
  }

  const extracao = diagnostico.extracao;

  return (
    <div className="space-y-8">
      <div>
        <Link href="/" className="text-sm text-tinta-fraca underline underline-offset-2">
          ← fila
        </Link>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-xl font-semibold tracking-tight">
            {diagnostico.arquivo.split("/").pop()}
          </h1>
          <span className="rounded border border-borda bg-white px-1.5 py-0.5 text-xs">
            {diagnostico.tipo}
          </span>
          {diagnostico.revisada_em && (
            <span className="rounded border border-emerald-300 bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-900">
              já revisado
            </span>
          )}
        </div>
        {extracao && (
          <p className="mt-1 font-mono text-xs text-tinta-fraca">
            {extracao.prompt} · {extracao.modelo} · US$ {extracao.custo_usd} ·{" "}
            {extracao.latencia_s}s{extracao.do_cache && " · do cache"}
          </p>
        )}
      </div>

      {/* Item 1 da tela: por que este documento está aqui. Vem antes do PDF de
          propósito — é a informação que o pipeline produziu e que nenhuma outra
          tela de revisão teria para mostrar. */}
      <section className="rounded-lg border border-borda bg-white p-5">
        <h2 className="text-sm font-semibold">Por que este documento está na fila</h2>
        <div className="mt-3">
          <PorQueEstaAqui sinais={diagnostico.sinais} />
        </div>
      </section>

      <AreaDeRevisao diagnostico={diagnostico} />

      {/* Item 2: o estado de cada sinal, inclusive os que passaram. Uma lista só
          de problemas não deixaria ver quanto do documento foi conferido. */}
      <section className="rounded-lg border border-borda bg-white p-5">
        <h2 className="text-sm font-semibold">O que cada sinal conseguiu afirmar</h2>
        <p className="mt-1 text-xs text-tinta-fraca">
          Inclui os que passaram: sem eles não dá para ver quanto do documento foi
          de fato verificado.
        </p>
        <div className="mt-4">
          <PainelDeSinais sinais={diagnostico.sinais} />
        </div>
      </section>
    </div>
  );
}
