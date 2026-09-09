import Link from "next/link";
import type { EstadoDoSinal, EstatisticasDaFila, TipoDeDocumento } from "@/lib/api";
import { nomeLegivel } from "@/lib/sinais";

export interface FiltroAtual {
  tipo?: TipoDeDocumento;
  sinal?: string;
  estado?: EstadoDoSinal;
  pendentes: boolean;
}

function comParametro(atual: FiltroAtual, mudanca: Partial<FiltroAtual>): string {
  const combinado = { ...atual, ...mudanca };
  const parametros = new URLSearchParams();
  if (combinado.tipo) parametros.set("tipo", combinado.tipo);
  if (combinado.sinal) parametros.set("sinal", combinado.sinal);
  if (combinado.estado) parametros.set("estado", combinado.estado);
  if (!combinado.pendentes) parametros.set("pendentes", "false");
  const texto = parametros.toString();
  return texto ? `/fila?${texto}` : "/fila";
}

function Pilula({
  href,
  ativo,
  children,
}: {
  href: string;
  ativo: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      aria-current={ativo ? "true" : undefined}
      className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
        ativo
          ? "border-tinta bg-tinta text-white"
          : "border-borda bg-white text-tinta hover:border-tinta-fraca"
      }`}
    >
      {children}
    </Link>
  );
}

/**
 * Os filtros, como links e não como formulário.
 *
 * Assim cada recorte da fila tem URL própria — dá para mandar "os documentos
 * que a aritmética não conseguiu conferir" para alguém — e a página inteira
 * continua renderizada no servidor, sem estado de cliente para sincronizar.
 *
 * O filtro por **estado** ao lado do filtro por sinal é o ponto: "aritmética
 * reprovou" e "aritmética não teve o que conferir" são duas filas de trabalho,
 * e sem separá-las a pessoa que abre a tela trata as duas do mesmo jeito.
 */
export function Filtros({
  atual,
  estatisticas,
}: {
  atual: FiltroAtual;
  estatisticas: EstatisticasDaFila;
}) {
  const sinais = Object.entries(estatisticas.por_sinal_que_bloqueia).sort(
    ([, a], [, b]) => b - a,
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs font-medium text-tinta-fraca">tipo</span>
        <Pilula href={comParametro(atual, { tipo: undefined })} ativo={!atual.tipo}>
          todos
        </Pilula>
        {(["boleto", "informe"] as const).map((tipo) => (
          <Pilula
            key={tipo}
            href={comParametro(atual, { tipo })}
            ativo={atual.tipo === tipo}
          >
            {tipo}
            {estatisticas.por_tipo[tipo] !== undefined && (
              <span className="ml-1.5 opacity-60">{estatisticas.por_tipo[tipo]}</span>
            )}
          </Pilula>
        ))}

        <span className="mx-2 h-4 w-px bg-borda" />

        <Pilula
          href={comParametro(atual, { pendentes: !atual.pendentes })}
          ativo={!atual.pendentes}
        >
          {atual.pendentes ? "mostrar já revisados" : "mostrando já revisados"}
        </Pilula>
      </div>

      {sinais.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-xs font-medium text-tinta-fraca">
            sinal que bloqueou
          </span>
          <Pilula href={comParametro(atual, { sinal: undefined })} ativo={!atual.sinal}>
            qualquer
          </Pilula>
          {sinais.map(([sinal, quantos]) => (
            <Pilula
              key={sinal}
              href={comParametro(atual, { sinal })}
              ativo={atual.sinal === sinal}
            >
              {nomeLegivel(sinal)}
              <span className="ml-1.5 opacity-60">{quantos}</span>
            </Pilula>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs font-medium text-tinta-fraca">o sinal</span>
        <Pilula href={comParametro(atual, { estado: undefined })} ativo={!atual.estado}>
          reprovou ou não conferiu
        </Pilula>
        <Pilula
          href={comParametro(atual, { estado: "divergente" })}
          ativo={atual.estado === "divergente"}
        >
          reprovou
        </Pilula>
        <Pilula
          href={comParametro(atual, { estado: "sem_cobertura" })}
          ativo={atual.estado === "sem_cobertura"}
        >
          não teve o que conferir
        </Pilula>
      </div>
    </div>
  );
}
