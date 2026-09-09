import Link from "next/link";
import {
  ApiIndisponivel,
  buscaEstatisticas,
  buscaFila,
  type EstadoDoSinal,
  type ItemDaFila,
  type TipoDeDocumento,
} from "@/lib/api";
import { AvisoDaApi } from "@/componentes/AvisoDaApi";
import { DataHora } from "@/componentes/DataHora";
import { Filtros, type FiltroAtual } from "@/componentes/Filtros";
import { nomeLegivel } from "@/lib/sinais";

const TIPOS = new Set(["boleto", "informe"]);
const ESTADOS = new Set(["conferido", "divergente", "sem_cobertura", "dispensado"]);

function primeiro(valor: string | string[] | undefined): string | undefined {
  return Array.isArray(valor) ? valor[0] : valor;
}

export default async function PaginaDaFila({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const parametros = await searchParams;
  const tipoBruto = primeiro(parametros.tipo);
  const estadoBruto = primeiro(parametros.estado);

  const atual: FiltroAtual = {
    tipo: tipoBruto && TIPOS.has(tipoBruto) ? (tipoBruto as TipoDeDocumento) : undefined,
    sinal: primeiro(parametros.sinal),
    estado:
      estadoBruto && ESTADOS.has(estadoBruto) ? (estadoBruto as EstadoDoSinal) : undefined,
    pendentes: primeiro(parametros.pendentes) !== "false",
  };

  try {
    const [pagina, estatisticas] = await Promise.all([
      buscaFila(atual),
      buscaEstatisticas(),
    ]);

    return (
      <div className="space-y-7">
        <div>
          <Link href="/" className="text-sm text-tinta-fraca underline underline-offset-2">
            ← casos da demonstração
          </Link>
          <h1 className="mt-2 text-xl font-semibold tracking-tight">Fila de revisão</h1>
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-tinta-fraca">
            Documentos que o pipeline não auto-aprovou. Um sinal reprovou, ou não
            teve o que conferir — e as duas coisas pedem trabalho diferente.
          </p>
        </div>

        <Resumo estatisticas={estatisticas} />
        <Filtros atual={atual} estatisticas={estatisticas} />

        <div>
          <p className="mb-3 text-xs text-tinta-fraca">
            {pagina.total === 0
              ? "nenhum documento neste recorte"
              : `${pagina.total} ${pagina.total === 1 ? "documento" : "documentos"}`}
          </p>
          {pagina.itens.length === 0 ? (
            <FilaVazia />
          ) : (
            <ul className="space-y-2">
              {pagina.itens.map((item) => (
                <li key={item.decisao_id}>
                  <Linha item={item} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    );
  } catch (erro) {
    if (erro instanceof ApiIndisponivel) return <AvisoDaApi erro={erro} />;
    throw erro;
  }
}

/**
 * As contagens que o relatório de eval mantém separadas, mantidas separadas aqui.
 *
 * Somar "auto-aprovados" com "bloqueados só por falta de cobertura" daria um
 * número que descreve duas situações diferentes — documento verificado e
 * documento sobre o qual ninguém afirmou nada. É a mesma razão do ADR 009.
 */
function Resumo({
  estatisticas,
}: {
  estatisticas: Awaited<ReturnType<typeof buscaEstatisticas>>;
}) {
  return (
    <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-borda bg-borda sm:grid-cols-4">
      <Numero rotulo="na fila" valor={estatisticas.pendentes} />
      <Numero rotulo="auto-aprovados" valor={estatisticas.auto_aprovados} />
      <Numero
        rotulo="só por falta de cobertura"
        valor={estatisticas.bloqueados_so_por_falta_de_cobertura}
        nota="nada reprovou, e nada foi conferido"
      />
      <Numero rotulo="correções feitas" valor={estatisticas.correcoes} />
    </dl>
  );
}

function Numero({
  rotulo,
  valor,
  nota,
}: {
  rotulo: string;
  valor: number;
  nota?: string;
}) {
  return (
    <div className="bg-white px-4 py-3">
      <dt className="text-xs text-tinta-fraca">{rotulo}</dt>
      <dd className="mt-0.5 text-2xl font-semibold tabular-nums">{valor}</dd>
      {nota && <p className="mt-0.5 text-[11px] leading-snug text-tinta-fraca">{nota}</p>}
    </div>
  );
}

function Linha({ item }: { item: ItemDaFila }) {
  const semCobertura = new Set(item.sem_cobertura);
  const reprovaram = item.sinais_que_bloqueiam.filter((s) => !semCobertura.has(s));
  const soFaltaCobertura = reprovaram.length === 0 && item.sem_cobertura.length > 0;

  return (
    <Link
      href={`/revisao/${item.decisao_id}`}
      className="block rounded-lg border border-borda bg-white px-4 py-3 transition-colors hover:border-tinta-fraca"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-sm font-medium">
          {item.arquivo.split("/").pop()}
        </span>
        <span className="rounded border border-borda px-1.5 py-px text-[11px] text-tinta-fraca">
          {item.tipo}
        </span>
        {item.achados > 0 && (
          <span className="rounded border border-rose-200 bg-rose-50 px-1.5 py-px text-[11px] text-rose-900">
            {item.achados} {item.achados === 1 ? "trecho suspeito" : "trechos suspeitos"}
          </span>
        )}
        {item.revisada_em && (
          <span className="rounded border border-emerald-200 bg-emerald-50 px-1.5 py-px text-[11px] text-emerald-900">
            revisado em <DataHora iso={item.revisada_em} precisao="data" />
          </span>
        )}
        <DataHora
          iso={item.criada_em}
          rotulo="processado em"
          className="ml-auto text-xs text-tinta-fraca"
        />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {reprovaram.map((sinal) => (
          <span
            key={sinal}
            className="rounded-full border border-rose-300 bg-rose-50 px-2 py-0.5 text-xs text-rose-900"
          >
            <span aria-hidden className="mr-1 font-mono">!</span>
            {nomeLegivel(sinal)} reprovou
          </span>
        ))}
        {item.sem_cobertura.map((sinal) => (
          <span
            key={sinal}
            className="rounded-full border border-dashed border-amber-400 bg-amber-50/60 px-2 py-0.5 text-xs text-amber-900"
          >
            <span aria-hidden className="mr-1 font-mono">—</span>
            {nomeLegivel(sinal)} não conferiu
          </span>
        ))}
      </div>

      {soFaltaCobertura && (
        <p className="mt-1.5 text-xs text-amber-800">
          Nada reprovou este documento. Ele está aqui porque ninguém conseguiu
          conferi-lo — precisa ser lido, não auditado.
        </p>
      )}
    </Link>
  );
}

function FilaVazia() {
  return (
    <div className="rounded-lg border border-dashed border-borda bg-white/60 px-5 py-8 text-center">
      <p className="text-sm font-medium">Nada aqui</p>
      <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-tinta-fraca">
        Ou o filtro não casa com nenhum documento, ou nada foi processado com a
        persistência ligada. O pipeline roda sem banco por padrão, e nesse modo
        as decisões não são gravadas.
      </p>
    </div>
  );
}
